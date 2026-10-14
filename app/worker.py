"""Taskiq worker. Run with: taskiq worker app.worker:broker"""

import os
import uuid

from taskiq import InMemoryBroker, SimpleRetryMiddleware

from app.config import get_settings
from app.db.session import get_sessionmaker
from app.services import build_pipeline, run_job

settings = get_settings()

if os.getenv("TASKIQ_IN_MEMORY") == "1":
    broker = InMemoryBroker()
else:
    from taskiq_redis import ListQueueBroker

    broker = ListQueueBroker(settings.redis_url)

broker = broker.with_middlewares(
    SimpleRetryMiddleware(default_retry_count=settings.max_job_attempts)
)

_pipeline = None


def get_pipeline():
    global _pipeline
    if _pipeline is None:
        _pipeline = build_pipeline(settings)
    return _pipeline


@broker.task(task_name="enrich_contact", retry_on_error=True)
async def enrich_contact(job_id: str) -> str | None:
    """Run one enrichment job. `run_job` is idempotent, so redelivery is safe."""
    with get_sessionmaker()() as session:
        job = await run_job(
            session, get_pipeline(), uuid.UUID(job_id), settings.max_job_attempts
        )
        return job.status.value if job else None
