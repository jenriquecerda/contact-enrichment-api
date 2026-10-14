from datetime import UTC, datetime, timedelta

from app.domain.models import Candidate, FieldName
from app.domain.resolver import FieldResolver, ResolverConfig

NOW = datetime(2026, 10, 1, tzinfo=UTC)


def cand(value, source, confidence=0.9, days_old=0, field=FieldName.TITLE):
    return Candidate(
        field=field,
        value=value,
        source=source,
        confidence=confidence,
        observed_at=NOW - timedelta(days=days_old),
    )


def resolver(**reliability):
    return FieldResolver(ResolverConfig(source_reliability=reliability), now=NOW)


def test_returns_none_without_candidates():
    assert resolver().resolve_field(FieldName.TITLE, []) is None


def test_agreeing_sources_raise_confidence():
    r = resolver(a=0.8, b=0.8)
    one = r.resolve_field(FieldName.TITLE, [cand("CTO", "a")])
    two = r.resolve_field(FieldName.TITLE, [cand("CTO", "a"), cand("cto", "b")])
    assert two.confidence > one.confidence
    assert two.sources == ["a", "b"]


def test_equivalent_values_are_grouped_by_normalized_form():
    r = resolver()
    result = r.resolve_field(
        FieldName.TITLE, [cand("Sr. Engineer", "a"), cand("senior engineer", "b")]
    )
    assert not result.conflict
    assert len(result.sources) == 2


def test_reliable_source_beats_unreliable_one():
    r = resolver(registry=0.95, scraper=0.3)
    result = r.resolve_field(
        FieldName.TITLE, [cand("VP Sales", "registry"), cand("Sales Rep", "scraper")]
    )
    assert result.value == "VP Sales"
    assert not result.conflict


def test_close_scores_are_flagged_as_conflict_with_penalty():
    r = resolver(a=0.8, b=0.78)
    result = r.resolve_field(FieldName.TITLE, [cand("CTO", "a"), cand("CEO", "b")])
    assert result.conflict
    assert result.confidence < 0.8 * 0.9
    assert "conflict" in result.reasoning


def test_stale_observations_decay():
    r = FieldResolver(
        ResolverConfig(source_reliability={"a": 0.9, "b": 0.9}, half_life_days=90), now=NOW
    )
    result = r.resolve_field(
        FieldName.TITLE,
        [cand("Old Title", "a", days_old=365), cand("New Title", "b", days_old=5)],
    )
    assert result.value == "New Title"


def test_resolve_groups_by_field():
    r = resolver()
    fields = r.resolve(
        [cand("CTO", "a"), cand("acme.com", "a", field=FieldName.DOMAIN)]
    )
    assert set(fields) == {FieldName.TITLE, FieldName.DOMAIN}
