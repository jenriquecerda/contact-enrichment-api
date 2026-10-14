import asyncio
from datetime import UTC, datetime, timedelta

from app.domain.models import Candidate, ContactInput, FieldName, ResolvedField
from app.llm.verifier import FallbackVerifier, HeuristicVerifier, Verdict

CONTACT = ContactInput(full_name="Ana Lopez", company="Acme", domain="acme.com")


def resolved(field, value, confidence=0.6, conflict=False):
    return ResolvedField(
        field=field, value=value, confidence=confidence, conflict=conflict,
        sources=["x"], reasoning="",
    )


def test_email_on_company_domain_gains_confidence():
    verdict = asyncio.run(
        HeuristicVerifier().verify(CONTACT, resolved(FieldName.EMAIL, "ana@acme.com"), [])
    )
    assert verdict.confidence > 0.6


def test_email_off_company_domain_loses_confidence():
    verdict = asyncio.run(
        HeuristicVerifier().verify(CONTACT, resolved(FieldName.EMAIL, "ana@gmail.com"), [])
    )
    assert verdict.confidence < 0.6


def test_conflicting_title_with_newer_observation_is_flagged():
    now = datetime(2026, 10, 1, tzinfo=UTC)
    candidates = [
        Candidate(field=FieldName.TITLE, value="Director", source="a", confidence=0.9,
                  observed_at=now - timedelta(days=200)),
        Candidate(field=FieldName.TITLE, value="VP Sales", source="b", confidence=0.9,
                  observed_at=now),
    ]
    verdict = asyncio.run(
        HeuristicVerifier().verify(
            CONTACT, resolved(FieldName.TITLE, "Director", conflict=True), candidates
        )
    )
    assert "job change" in verdict.reasoning


class _Broken:
    name = "broken"

    async def verify(self, *_):
        raise RuntimeError("upstream 529")


class _Slow:
    name = "slow"

    async def verify(self, *_):
        await asyncio.sleep(1)
        return Verdict("x", 1.0, "", "slow")


def test_fallback_used_when_primary_errors():
    verifier = FallbackVerifier(_Broken(), HeuristicVerifier())
    verdict = asyncio.run(verifier.verify(CONTACT, resolved(FieldName.TITLE, "CTO"), []))
    assert verdict.verifier == "heuristic"


def test_fallback_used_when_primary_times_out():
    verifier = FallbackVerifier(_Slow(), HeuristicVerifier(), timeout=0.01)
    verdict = asyncio.run(verifier.verify(CONTACT, resolved(FieldName.TITLE, "CTO"), []))
    assert verdict.verifier == "heuristic"


def test_fallback_used_when_no_primary_configured():
    verifier = FallbackVerifier(None, HeuristicVerifier())
    verdict = asyncio.run(verifier.verify(CONTACT, resolved(FieldName.TITLE, "CTO"), []))
    assert verdict.verifier == "heuristic"
