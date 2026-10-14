"""Application services: wiring the pipeline, the job lifecycle and persistence."""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.cache import Cache, InMemoryCache, RedisCache
from app.config import Settings
from app.db.models import Contact, ContactField, EnrichmentJob, JobStatus
from app.domain.models import ContactInput, EnrichmentResult
from app.domain.resolver import FieldResolver, ResolverConfig
from app.llm.verifier import AnthropicVerifier, FallbackVerifier, HeuristicVerifier
from app.pipeline import EnrichmentPipeline, PipelineConfig
from app.sources.email_pattern import EmailPatternSource
from app.sources.fixtures import default_sources

log = logging.getLogger(__name__)

OPEN_STATUSES = (JobStatus.QUEUED, JobStatus.RUNNING)


def build_pipeline(settings: Settings, cache: Cache | None = None) -> EnrichmentPipeline:
    primary = (
        AnthropicVerifier(
            settings.anthropic_api_key, settings.anthropic_model, settings.llm_timeout_seconds
        )
        if settings.anthropic_api_key
        else None
    )
    return EnrichmentPipeline(
        sources=[*default_sources(), EmailPatternSource(settings.email_patterns)],
        resolver=FieldResolver(ResolverConfig(source_reliability=settings.source_reliability)),
        verifier=FallbackVerifier(primary, HeuristicVerifier()),
        cache=cache or (RedisCache(settings.redis_url) if settings.redis_url else InMemoryCache()),
        config=PipelineConfig(
            cache_ttl_seconds=settings.cache_ttl_seconds,
            verify_below_confidence=settings.verify_below_confidence,
        ),
    )


def open_or_create_job(session: Session, contact_id: uuid.UUID) -> tuple[EnrichmentJob, bool]:
    """Idempotent enqueue: reuse a queued/running job for the contact if there is one.

    Returns (job, created).
    """
    existing = session.scalars(
        select(EnrichmentJob)
        .where(EnrichmentJob.contact_id == contact_id, EnrichmentJob.status.in_(OPEN_STATUSES))
        .order_by(EnrichmentJob.created_at.desc())
        .limit(1)
    ).first()
    if existing:
        return existing, False
    job = EnrichmentJob(contact_id=contact_id, status=JobStatus.QUEUED)
    session.add(job)
    session.commit()
    return job, True


def _to_input(contact: Contact) -> ContactInput:
    return ContactInput(
        full_name=contact.full_name,
        company=contact.company,
        email=contact.email,
        domain=contact.domain,
    )


def save_result(session: Session, job: EnrichmentJob, result: EnrichmentResult) -> None:
    """Write resolved fields as the new current values; keep old rows as history."""
    if result.fields:
        session.execute(
            update(ContactField)
            .where(
                ContactField.contact_id == job.contact_id,
                ContactField.field.in_([f.value for f in result.fields]),
                ContactField.is_current.is_(True),
            )
            .values(is_current=False)
        )
    for name, resolved in result.fields.items():
        session.add(
            ContactField(
                contact_id=job.contact_id,
                job_id=job.id,
                field=name.value,
                value=resolved.value,
                confidence=resolved.confidence,
                conflict=resolved.conflict,
                sources=resolved.sources,
                reasoning=resolved.reasoning,
                is_current=True,
            )
        )
    job.source_errors = result.source_errors


class JobWillRetry(Exception):
    """Raised so the queue retries the job; the job is back in `queued`."""


async def run_job(
    session: Session, pipeline: EnrichmentPipeline, job_id: uuid.UUID, max_attempts: int
) -> EnrichmentJob | None:
    job = session.get(EnrichmentJob, job_id, with_for_update=True)
    if job is None or job.status not in OPEN_STATUSES:
        # Unknown or already finished: a duplicate delivery, nothing to do. Commit (not
        # rollback) to release the row lock without expiring the job for the caller.
        session.commit()
        return job

    job.status = JobStatus.RUNNING
    job.attempts += 1
    job.started_at = datetime.now(UTC)
    job.error = None
    session.commit()

    try:
        result = await pipeline.run(_to_input(job.contact))
        save_result(session, job, result)
        job.status = JobStatus.SUCCEEDED
        job.finished_at = datetime.now(UTC)
        session.commit()
        return job
    except Exception as exc:
        session.rollback()
        job = session.get(EnrichmentJob, job_id)
        job.error = f"{type(exc).__name__}: {exc}"[:1000]
        if job.attempts < max_attempts:
            job.status = JobStatus.QUEUED
            session.commit()
            log.warning("job %s attempt %s failed, will retry: %s", job_id, job.attempts, exc)
            raise JobWillRetry(str(job_id)) from exc
        job.status = JobStatus.FAILED
        job.finished_at = datetime.now(UTC)
        session.commit()
        log.error("job %s failed after %s attempts: %s", job_id, job.attempts, exc)
        return job
