"""Fixture-backed sources so the service runs end to end without paid providers.

Each source reads a JSON file keyed by normalized name + company. Real providers
implement the same `Source` protocol.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from app.domain.models import Candidate, ContactInput, FieldName
from app.domain.normalize import normalize_company
from app.sources.base import SourceError

DATA_DIR = Path(__file__).parent / "data"


def contact_key(contact: ContactInput) -> str:
    company = normalize_company(contact.company) if contact.company else ""
    return f"{contact.full_name.strip().lower()}|{company}"


class FixtureSource:
    def __init__(self, name: str, records: dict[str, dict], confidence: float):
        self.name = name
        self._records = records
        self._confidence = confidence

    @classmethod
    def from_file(cls, name: str, path: Path, confidence: float) -> "FixtureSource":
        try:
            records = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise SourceError(f"cannot load fixtures for {name}: {exc}") from exc
        return cls(name, records, confidence)

    def cache_key(self, contact: ContactInput) -> str:
        return contact_key(contact)

    async def fetch(self, contact: ContactInput) -> list[Candidate]:
        record = self._records.get(contact_key(contact))
        if not record:
            return []
        observed = datetime.fromisoformat(record.get("observed_at", "2026-01-01T00:00:00+00:00"))
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        return [
            Candidate(
                field=FieldName(field),
                value=value,
                source=self.name,
                confidence=self._confidence,
                observed_at=observed,
            )
            for field, value in record.get("fields", {}).items()
        ]


def default_sources() -> list[FixtureSource]:
    return [
        FixtureSource.from_file("company_registry", DATA_DIR / "company_registry.json", 0.95),
        FixtureSource.from_file("professional_profiles", DATA_DIR / "profiles.json", 0.85),
        FixtureSource.from_file("web_mentions", DATA_DIR / "web_mentions.json", 0.6),
    ]
