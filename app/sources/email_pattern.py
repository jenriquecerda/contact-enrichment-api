"""Infer a work email from the person's name and the company's known email pattern."""

import unicodedata

from app.domain.models import Candidate, ContactInput, FieldName
from app.domain.normalize import email_domain, normalize_domain

PATTERNS = {
    "first.last": lambda first, last: f"{first}.{last}",
    "flast": lambda first, last: f"{first[0]}{last}",
    "first": lambda first, last: first,
    "firstl": lambda first, last: f"{first}{last[0]}",
    "first_last": lambda first, last: f"{first}_{last}",
}


def _ascii_token(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return "".join(ch for ch in folded.lower() if ch.isalnum())


class EmailPatternSource:
    """Known pattern for the domain -> one confident guess; unknown -> no guess."""

    name = "email_pattern"

    def __init__(self, domain_patterns: dict[str, str], confidence: float = 0.7):
        self._patterns = {normalize_domain(d): p for d, p in domain_patterns.items()}
        self._confidence = confidence

    def cache_key(self, contact: ContactInput) -> str:
        return f"{contact.full_name.lower()}|{self._domain(contact) or ''}"

    @staticmethod
    def _domain(contact: ContactInput) -> str | None:
        if contact.domain:
            return normalize_domain(contact.domain)
        if contact.email:
            return email_domain(contact.email)
        return None

    async def fetch(self, contact: ContactInput) -> list[Candidate]:
        domain = self._domain(contact)
        names = [_ascii_token(p) for p in contact.full_name.split()]
        names = [n for n in names if n]
        if not domain or len(names) < 2 or domain not in self._patterns:
            return []
        local = PATTERNS[self._patterns[domain]](names[0], names[-1])
        return [
            Candidate(
                field=FieldName.EMAIL,
                value=f"{local}@{domain}",
                source=self.name,
                confidence=self._confidence,
            )
        ]
