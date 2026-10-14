"""Source interface. A source turns what we know about a contact into candidates."""

from typing import Protocol

from app.domain.models import Candidate, ContactInput


class SourceError(Exception):
    """Permanent failure: retrying will not help (bad request, not found, auth)."""


class TransientSourceError(SourceError):
    """Temporary failure: timeouts, 429s, 5xx. Safe to retry."""


class Source(Protocol):
    name: str

    def cache_key(self, contact: ContactInput) -> str:
        """Stable key for caching this source's answer for this contact."""
        ...

    async def fetch(self, contact: ContactInput) -> list[Candidate]: ...
