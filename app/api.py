"""HTTP API. Run with: uvicorn app.api:app --reload"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Contact, ContactField, EnrichmentJob
from app.db.session import get_session
from app.domain.models import ContactInput
from app.domain.normalize import normalize_domain, normalize_email
from app.services import open_or_create_job

app = FastAPI(title="Contact Enrichment API", version="0.1.0")

SessionDep = Annotated[Session, Depends(get_session)]


class FieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    field: str
    value: str
    confidence: float
    conflict: bool
    sources: list[str]
    reasoning: str
    resolved_at: datetime


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    company: str | None
    email: str | None
    domain: str | None
    created_at: datetime
    fields: list[FieldOut] = []


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    contact_id: uuid.UUID
    status: str
    attempts: int
    error: str | None
    source_errors: dict[str, str]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


def enqueue(job_id: uuid.UUID) -> None:
    """Hand the job to the worker. Overridden in tests."""
    import anyio

    from app.worker import enrich_contact

    anyio.from_thread.run(enrich_contact.kiq, str(job_id))


def get_enqueue():
    return enqueue


EnqueueDep = Annotated[object, Depends(get_enqueue)]


def _get_contact(session: Session, contact_id: uuid.UUID) -> Contact:
    contact = session.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "contact not found")
    return contact


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/contacts", status_code=status.HTTP_201_CREATED, response_model=ContactOut)
def create_contact(body: ContactInput, session: SessionDep) -> ContactOut:
    contact = Contact(
        full_name=body.full_name.strip(),
        company=body.company.strip() if body.company else None,
        email=normalize_email(body.email) if body.email else None,
        domain=normalize_domain(body.domain) if body.domain else None,
    )
    session.add(contact)
    session.commit()
    return ContactOut(
        id=contact.id,
        full_name=contact.full_name,
        company=contact.company,
        email=contact.email,
        domain=contact.domain,
        created_at=contact.created_at,
    )


@app.get("/contacts/{contact_id}", response_model=ContactOut)
def get_contact(contact_id: uuid.UUID, session: SessionDep) -> ContactOut:
    contact = _get_contact(session, contact_id)
    fields = session.scalars(
        select(ContactField)
        .where(ContactField.contact_id == contact_id, ContactField.is_current.is_(True))
        .order_by(ContactField.field)
    ).all()
    return ContactOut(
        id=contact.id,
        full_name=contact.full_name,
        company=contact.company,
        email=contact.email,
        domain=contact.domain,
        created_at=contact.created_at,
        fields=[FieldOut.model_validate(f) for f in fields],
    )


@app.post(
    "/contacts/{contact_id}/enrich",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobOut,
)
def enrich_contact(contact_id: uuid.UUID, session: SessionDep, enqueue_job: EnqueueDep):
    _get_contact(session, contact_id)
    job, created = open_or_create_job(session, contact_id)
    if created:
        enqueue_job(job.id)
    return job


@app.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, session: SessionDep) -> EnrichmentJob:
    job = session.get(EnrichmentJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return job
