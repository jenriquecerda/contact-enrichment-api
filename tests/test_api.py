import asyncio
import uuid

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from app.cache import InMemoryCache  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db.models import EnrichmentJob, JobStatus  # noqa: E402
from app.services import JobWillRetry, build_pipeline, run_job  # noqa: E402

ANA = {"full_name": "Ana Lopez", "company": "Acme, Inc.", "domain": "https://www.acme.com"}


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_create_contact_normalizes_input(client):
    response = client.post("/contacts", json=ANA)
    assert response.status_code == 201
    assert response.json()["domain"] == "acme.com"


def test_create_contact_validates_input(client):
    assert client.post("/contacts", json={"full_name": ""}).status_code == 422


def test_unknown_contact_is_404(client):
    assert client.get(f"/contacts/{uuid.uuid4()}").status_code == 404


def test_enrich_is_idempotent_while_a_job_is_open(client, enqueued):
    contact_id = client.post("/contacts", json=ANA).json()["id"]
    first = client.post(f"/contacts/{contact_id}/enrich")
    second = client.post(f"/contacts/{contact_id}/enrich")
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert len(enqueued) == 1


def _pipeline():
    return build_pipeline(Settings(anthropic_api_key=None), cache=InMemoryCache())


def test_job_runs_and_fields_are_returned(client, session_factory, enqueued):
    contact_id = client.post("/contacts", json=ANA).json()["id"]
    job_id = client.post(f"/contacts/{contact_id}/enrich").json()["id"]

    with session_factory() as session:
        job = asyncio.run(run_job(session, _pipeline(), uuid.UUID(job_id), max_attempts=3))
    assert job.status == JobStatus.SUCCEEDED

    job_body = client.get(f"/jobs/{job_id}").json()
    assert job_body["attempts"] == 1

    fields = {f["field"]: f for f in client.get(f"/contacts/{contact_id}").json()["fields"]}
    assert fields["domain"]["value"] == "acme.com"
    assert fields["email"]["value"] == "ana.lopez@acme.com"
    assert fields["title"]["sources"]


def test_re_enrichment_keeps_one_current_value_per_field(client, session_factory):
    contact_id = client.post("/contacts", json=ANA).json()["id"]
    for _ in range(2):
        job_id = client.post(f"/contacts/{contact_id}/enrich").json()["id"]
        with session_factory() as session:
            asyncio.run(run_job(session, _pipeline(), uuid.UUID(job_id), max_attempts=3))
    names = [f["field"] for f in client.get(f"/contacts/{contact_id}").json()["fields"]]
    assert len(names) == len(set(names))


class _Exploding:
    async def run(self, contact):
        raise RuntimeError("boom")


def test_failing_job_is_requeued_then_failed(client, session_factory):
    contact_id = client.post("/contacts", json=ANA).json()["id"]
    job_id = uuid.UUID(client.post(f"/contacts/{contact_id}/enrich").json()["id"])

    with session_factory() as session:
        with pytest.raises(JobWillRetry):
            asyncio.run(run_job(session, _Exploding(), job_id, max_attempts=2))
        assert session.get(EnrichmentJob, job_id).status == JobStatus.QUEUED

        job = asyncio.run(run_job(session, _Exploding(), job_id, max_attempts=2))
        assert job.status == JobStatus.FAILED
        assert job.attempts == 2
        assert "boom" in job.error


def test_finished_job_is_not_run_again(client, session_factory):
    contact_id = client.post("/contacts", json=ANA).json()["id"]
    job_id = uuid.UUID(client.post(f"/contacts/{contact_id}/enrich").json()["id"])
    with session_factory() as session:
        asyncio.run(run_job(session, _pipeline(), job_id, max_attempts=3))
        again = asyncio.run(run_job(session, _Exploding(), job_id, max_attempts=3))
    assert again.status == JobStatus.SUCCEEDED
    assert again.attempts == 1
