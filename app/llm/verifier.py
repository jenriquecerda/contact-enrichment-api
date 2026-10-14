"""Second opinion on low-confidence or conflicting fields.

The LLM is optional. `FallbackVerifier` always returns an answer: it asks the
primary verifier and falls back to deterministic heuristics on timeout, error,
malformed output or missing API key.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Protocol

from app.domain.models import Candidate, ContactInput, FieldName, ResolvedField
from app.domain.normalize import email_domain, normalize

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Verdict:
    value: str
    confidence: float
    reasoning: str
    verifier: str


class Verifier(Protocol):
    name: str

    async def verify(
        self, contact: ContactInput, resolved: ResolvedField, candidates: list[Candidate]
    ) -> Verdict: ...


class HeuristicVerifier:
    """Deterministic checks that need no network."""

    name = "heuristic"

    async def verify(self, contact, resolved, candidates) -> Verdict:
        confidence = resolved.confidence
        notes = []

        if resolved.field == FieldName.EMAIL:
            domain = email_domain(resolved.value)
            known = {
                normalize(FieldName.DOMAIN, c.value)
                for c in candidates
                if c.field == FieldName.DOMAIN
            }
            if contact.domain:
                known.add(normalize(FieldName.DOMAIN, contact.domain))
            if known and domain in known:
                confidence = min(1.0, confidence + 0.1)
                notes.append("email domain matches the company domain")
            elif known:
                confidence *= 0.6
                notes.append("email domain does not match the company domain")

        if resolved.field == FieldName.TITLE and resolved.conflict:
            newest = max(
                (c for c in candidates if c.field == FieldName.TITLE),
                key=lambda c: c.observed_at,
            )
            if normalize(FieldName.TITLE, newest.value) != normalize(
                FieldName.TITLE, resolved.value
            ):
                notes.append(f"newest observation says '{newest.value}'; possible job change")
                confidence *= 0.8

        return Verdict(
            value=resolved.value,
            confidence=round(confidence, 4),
            reasoning="; ".join(notes) or "no heuristic adjustments",
            verifier=self.name,
        )


class AnthropicVerifier:
    """Asks Claude to pick the most likely value among the candidates, as JSON."""

    name = "llm"

    def __init__(self, api_key: str, model: str, timeout: float = 15.0):
        import httpx  # lazy: only needed when an API key is configured

        self._client = httpx.AsyncClient(
            base_url="https://api.anthropic.com",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            timeout=timeout,
        )
        self._model = model

    def _prompt(self, contact, resolved, candidates) -> str:
        rows = [
            {"value": c.value, "source": c.source, "observed_at": c.observed_at.isoformat()}
            for c in candidates
            if c.field == resolved.field
        ]
        return (
            "You verify CRM contact data. Pick the most likely current value for the field "
            "from the candidates only; never invent a value.\n"
            f"Contact: {contact.model_dump_json()}\n"
            f"Field: {resolved.field.value}\n"
            f"Candidates: {json.dumps(rows)}\n"
            'Answer with JSON only: {"value": str, "confidence": 0..1, "reasoning": str}'
        )

    async def verify(self, contact, resolved, candidates) -> Verdict:
        response = await self._client.post(
            "/v1/messages",
            json={
                "model": self._model,
                "max_tokens": 300,
                "messages": [
                    {"role": "user", "content": self._prompt(contact, resolved, candidates)}
                ],
            },
        )
        response.raise_for_status()
        text = response.json()["content"][0]["text"]
        data = json.loads(text)
        allowed = {
            normalize(resolved.field, c.value) for c in candidates if c.field == resolved.field
        }
        if normalize(resolved.field, data["value"]) not in allowed:
            raise ValueError("LLM returned a value that is not among the candidates")
        return Verdict(
            value=data["value"],
            confidence=max(0.0, min(1.0, float(data["confidence"]))),
            reasoning=str(data["reasoning"])[:500],
            verifier=self.name,
        )


class FallbackVerifier:
    name = "fallback"

    def __init__(self, primary: Verifier | None, fallback: Verifier, timeout: float = 20.0):
        self._primary = primary
        self._fallback = fallback
        self._timeout = timeout

    async def verify(self, contact, resolved, candidates) -> Verdict:
        if self._primary is not None:
            try:
                return await asyncio.wait_for(
                    self._primary.verify(contact, resolved, candidates), timeout=self._timeout
                )
            except Exception as exc:  # noqa: BLE001 - any failure falls back
                log.warning("primary verifier failed, using fallback: %s", exc)
        return await self._fallback.verify(contact, resolved, candidates)
