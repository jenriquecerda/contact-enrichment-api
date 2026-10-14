"""Normalization so equivalent values from different sources compare equal."""

import re
from urllib.parse import urlparse

from app.domain.models import FieldName

_WS = re.compile(r"\s+")
_COMPANY_SUFFIXES = re.compile(
    r"[,\s]+(inc|inc\.|llc|ltd|ltd\.|corp|corp\.|corporation|co\.|s\.a\. de c\.v\.|gmbh)$",
    re.IGNORECASE,
)
_TITLE_ABBREVIATIONS = {
    "sr": "senior",
    "sr.": "senior",
    "jr": "junior",
    "jr.": "junior",
    "vp": "vice president",
    "mgr": "manager",
    "eng": "engineer",
}


def collapse_ws(value: str) -> str:
    return _WS.sub(" ", value).strip()


def normalize_email(value: str) -> str:
    return value.strip().lower()


def normalize_domain(value: str) -> str:
    value = value.strip().lower()
    if "://" in value:
        value = urlparse(value).netloc
    value = value.split("/")[0]
    return value.removeprefix("www.")


def normalize_company(value: str) -> str:
    value = collapse_ws(value)
    value = _COMPANY_SUFFIXES.sub("", value)
    return value.lower()


def normalize_title(value: str) -> str:
    words = collapse_ws(value).lower().split(" ")
    return " ".join(_TITLE_ABBREVIATIONS.get(w, w) for w in words)


def normalize_linkedin(value: str) -> str:
    value = value.strip().lower().rstrip("/")
    value = value.removeprefix("https://").removeprefix("http://").removeprefix("www.")
    return value


_NORMALIZERS = {
    FieldName.EMAIL: normalize_email,
    FieldName.DOMAIN: normalize_domain,
    FieldName.COMPANY: normalize_company,
    FieldName.TITLE: normalize_title,
    FieldName.LINKEDIN_URL: normalize_linkedin,
    FieldName.LOCATION: lambda v: collapse_ws(v).lower(),
}


def normalize(field: FieldName, value: str) -> str:
    """Comparison key for a field value. Display values are kept separately."""
    return _NORMALIZERS[field](value)


def email_domain(email: str) -> str | None:
    _, _, domain = normalize_email(email).partition("@")
    return domain or None
