from app.domain.models import FieldName
from app.domain.normalize import email_domain, normalize


def test_email_is_case_and_space_insensitive():
    assert normalize(FieldName.EMAIL, "  Ana.Lopez@Acme.COM ") == "ana.lopez@acme.com"


def test_domain_strips_scheme_path_and_www():
    assert normalize(FieldName.DOMAIN, "https://www.acme.com/about") == "acme.com"
    assert normalize(FieldName.DOMAIN, "ACME.com") == "acme.com"


def test_company_drops_legal_suffixes():
    assert normalize(FieldName.COMPANY, "Acme, Inc.") == normalize(FieldName.COMPANY, "acme")
    assert normalize(FieldName.COMPANY, "Grupo Norte S.A. de C.V.") == "grupo norte"


def test_title_expands_abbreviations():
    assert normalize(FieldName.TITLE, "Sr. Software Eng") == "senior software engineer"
    assert normalize(FieldName.TITLE, "VP  Sales") == "vice president sales"


def test_linkedin_ignores_scheme_and_trailing_slash():
    a = normalize(FieldName.LINKEDIN_URL, "https://www.linkedin.com/in/ana-lopez/")
    b = normalize(FieldName.LINKEDIN_URL, "linkedin.com/in/ana-lopez")
    assert a == b


def test_email_domain():
    assert email_domain("ana@acme.com") == "acme.com"
    assert email_domain("not-an-email") is None
