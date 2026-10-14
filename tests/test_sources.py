import asyncio

from app.domain.models import ContactInput, FieldName
from app.sources.email_pattern import EmailPatternSource
from app.sources.fixtures import default_sources


def test_fixture_sources_return_candidates_for_known_contact():
    contact = ContactInput(full_name="Ana Lopez", company="Acme, Inc.")
    results = [asyncio.run(s.fetch(contact)) for s in default_sources()]
    fields = {c.field for batch in results for c in batch}
    assert FieldName.TITLE in fields
    assert FieldName.DOMAIN in fields


def test_fixture_sources_return_nothing_for_unknown_contact():
    contact = ContactInput(full_name="Nobody Here", company="Nowhere")
    assert all(asyncio.run(s.fetch(contact)) == [] for s in default_sources())


def test_email_pattern_uses_known_domain_pattern():
    source = EmailPatternSource({"acme.com": "first.last"})
    contact = ContactInput(full_name="Ana María López", domain="https://acme.com")
    [candidate] = asyncio.run(source.fetch(contact))
    assert candidate.value == "ana.lopez@acme.com"


def test_email_pattern_skips_unknown_domain_and_single_names():
    source = EmailPatternSource({"acme.com": "flast"})
    assert asyncio.run(source.fetch(ContactInput(full_name="Ana Lopez", domain="other.com"))) == []
    assert asyncio.run(source.fetch(ContactInput(full_name="Ana", domain="acme.com"))) == []
