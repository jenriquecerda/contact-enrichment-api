"""Enrichment pipeline: fetch from all sources, resolve, verify weak fields."""

import asyncio
import logging
from dataclasses import dataclass

from app.cache import Cache
from app.domain.models import Candidate, ContactInput, EnrichmentResult
from app.domain.resolver import FieldResolver
from app.llm.verifier import Verifier
from app.retry import RetryPolicy, with_retry
from app.sources.base import Source

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineConfig:
    cache_ttl_seconds: int = 6 * 3600
    verify_below_confidence: float = 0.75


class EnrichmentPipeline:
    def __init__(
        self,
        sources: list[Source],
        resolver: FieldResolver,
        verifier: Verifier,
        cache: Cache,
        retry: RetryPolicy | None = None,
        config: PipelineConfig | None = None,
    ):
        self.sources = sources
        self.resolver = resolver
        self.verifier = verifier
        self.cache = cache
        self.retry = retry or RetryPolicy()
        self.config = config or PipelineConfig()

    async def _fetch_one(self, source: Source, contact: ContactInput) -> list[Candidate]:
        key = f"{source.name}:{source.cache_key(contact)}"
        cached = await self.cache.get(key)
        if cached is not None:
            return [Candidate.model_validate(c) for c in cached]
        candidates = await with_retry(lambda: source.fetch(contact), self.retry)
        await self.cache.set(
            key, [c.model_dump(mode="json") for c in candidates], self.config.cache_ttl_seconds
        )
        return candidates

    async def gather(self, contact: ContactInput) -> tuple[list[Candidate], dict[str, str]]:
        results = await asyncio.gather(
            *(self._fetch_one(s, contact) for s in self.sources), return_exceptions=True
        )
        candidates: list[Candidate] = []
        errors: dict[str, str] = {}
        for source, result in zip(self.sources, results, strict=True):
            if isinstance(result, BaseException):
                log.warning("source %s failed: %r", source.name, result)
                errors[source.name] = f"{type(result).__name__}: {result}"[:200]
            else:
                candidates.extend(result)
        return candidates, errors

    async def run(self, contact: ContactInput) -> EnrichmentResult:
        candidates, errors = await self.gather(contact)
        fields = self.resolver.resolve(candidates)

        for name, resolved in list(fields.items()):
            if resolved.confidence >= self.config.verify_below_confidence and not resolved.conflict:
                continue
            verdict = await self.verifier.verify(contact, resolved, candidates)
            fields[name] = resolved.model_copy(
                update={
                    "value": verdict.value,
                    "confidence": verdict.confidence,
                    "reasoning": f"{resolved.reasoning} Verified ({verdict.verifier}): "
                    f"{verdict.reasoning}.",
                }
            )
        return EnrichmentResult(fields=fields, source_errors=errors)
