"""Domain types shared by sources, the resolver and the API."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class FieldName(StrEnum):
    EMAIL = "email"
    TITLE = "title"
    COMPANY = "company"
    DOMAIN = "domain"
    LOCATION = "location"
    LINKEDIN_URL = "linkedin_url"


class ContactInput(BaseModel):
    """What we know about a contact before enrichment."""

    full_name: str = Field(min_length=1, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    domain: str | None = Field(default=None, max_length=253)


class Candidate(BaseModel):
    """One source's answer for one field."""

    field: FieldName
    value: str
    source: str
    confidence: float = Field(ge=0.0, le=1.0)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ResolvedField(BaseModel):
    field: FieldName
    value: str
    confidence: float = Field(ge=0.0, le=1.0)
    conflict: bool = False
    sources: list[str]
    reasoning: str


class EnrichmentResult(BaseModel):
    fields: dict[FieldName, ResolvedField]
    source_errors: dict[str, str] = Field(default_factory=dict)
