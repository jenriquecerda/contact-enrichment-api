import asyncio
from datetime import UTC, datetime

from app.cache import InMemoryCache
from app.domain.models import Candidate, ContactInput, FieldName
from app.domain.resolver import FieldResolver, ResolverConfig
from app.llm.verifier import FallbackVerifier, HeuristicVerifier
from app.pipeline import EnrichmentPipeline
from app.retry import RetryPolicy
from app.sources.base import SourceError, TransientSourceError
from app.sources.email_pattern import EmailPatternSource
from app.sources.fixtures import default_sources

NOW = datetime(2026, 10, 1, tzinfo=UTC)


class CountingSource:
    def __init__(self, name, candidates=(), fail_times=0, permanent=False):
        self.name = name
        self.calls = 0
        self._candidates = list(candidates)
        self._fail_times = fail_times
        self._permanent = permanent

    def cache_key(self, contact):
        return contact.full_name

    async def fetch(self, contact):
        self.calls += 1
        if self._permanent:
            raise SourceError("401 unauthorized")
        if self.calls <= self._fail_times:
            raise TransientSourceError("503")
        return self._candidates


def build(sources):
    return EnrichmentPipeline(
        sources=sources,
        resolver=FieldResolver(ResolverConfig(), now=NOW),
        verifier=FallbackVerifier(None, HeuristicVerifier()),
        cache=InMemoryCache(),
        retry=RetryPolicy(max_attempts=3, base_delay=0, max_delay=0),
    )


CONTACT = ContactInput(full_name="Ana Lopez", company="Acme")


def title(value, source):
    return Candidate(field=FieldName.TITLE, value=value, source=source, confidence=0.9,
                     observed_at=NOW)


def test_end_to_end_with_fixture_sources():
    pipeline = build(default_sources() + [EmailPatternSource({"acme.com": "first.last"})])
    contact = ContactInput(full_name="Ana Lopez", company="Acme", domain="acme.com")
    result = asyncio.run(pipeline.run(contact))
    assert result.fields[FieldName.DOMAIN].value == "acme.com"
    assert result.fields[FieldName.TITLE].value == "VP of Revenue Operations"
    assert result.fields[FieldName.EMAIL].value == "ana.lopez@acme.com"
    assert result.source_errors == {}


def test_a_failing_source_does_not_fail_the_run():
    good = CountingSource("good", [title("CTO", "good")])
    bad = CountingSource("bad", permanent=True)
    result = asyncio.run(build([good, bad]).run(CONTACT))
    assert result.fields[FieldName.TITLE].value == "CTO"
    assert "bad" in result.source_errors
    assert bad.calls == 1


def test_transient_failures_are_retried():
    flaky = CountingSource("flaky", [title("CTO", "flaky")], fail_times=2)
    result = asyncio.run(build([flaky]).run(CONTACT))
    assert flaky.calls == 3
    assert FieldName.TITLE in result.fields


def test_results_are_cached_per_source_and_contact():
    source = CountingSource("s", [title("CTO", "s")])
    pipeline = build([source])
    asyncio.run(pipeline.run(CONTACT))
    asyncio.run(pipeline.run(CONTACT))
    assert source.calls == 1


def test_low_confidence_fields_are_verified():
    weak = Candidate(field=FieldName.TITLE, value="CTO", source="w", confidence=0.3,
                     observed_at=NOW)
    result = asyncio.run(build([CountingSource("w", [weak])]).run(CONTACT))
    assert "Verified (heuristic)" in result.fields[FieldName.TITLE].reasoning
