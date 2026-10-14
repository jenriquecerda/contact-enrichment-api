# Spec: Contact Enrichment API

## Problem

CRM records go stale: people change jobs, companies rebrand, emails bounce. Teams need a
service that takes a partial contact (name, company, maybe an email) and returns verified
fields with enough evidence that a RevOps user can decide whether to trust each one.

## Goals

- Enrich a contact from several independent sources in one request.
- Resolve conflicts between sources deterministically, with a confidence score per field.
- Explain every answer: which sources agreed, which disagreed, and why the winner won.
- Run enrichment asynchronously so API latency does not depend on slow sources.
- Degrade gracefully: a failing source or LLM call lowers confidence, it never fails the job.

## Non-goals (v1)

- Real third-party data providers (sources are pluggable; v1 ships fixture-backed sources).
- Bulk CSV import and CRM sync.
- Authentication and multi-tenancy.

## API

| Method | Path | Behaviour |
| --- | --- | --- |
| POST | `/contacts` | Create a contact from partial input. 201. |
| GET | `/contacts/{id}` | Contact plus its latest resolved fields. |
| POST | `/contacts/{id}/enrich` | Queue an enrichment job. 202 with the job. Idempotent: returns the open job if one is already queued or running. |
| GET | `/jobs/{id}` | Job status, attempts and error. |
| GET | `/healthz` | Liveness. |

## Enrichment pipeline

1. **Normalize** input (lowercase emails and domains, strip titles and whitespace).
2. **Fetch** from every source concurrently. Each source call has a timeout and is retried
   with exponential backoff and jitter on transient errors only. Results are cached per
   `(source, lookup key)` with a TTL so repeated jobs do not hammer providers.
3. **Resolve** each field: candidates are grouped by normalized value; each group's score
   combines source reliability, the source's own confidence and recency
   (`1 - Π(1 - reliability × confidence × decay)`). The top group wins. If the runner-up is
   within a margin, the field is flagged `conflict` and confidence is reduced.
4. **Verify** low-confidence or conflicting fields with an LLM verifier. The LLM sits behind
   an interface with a deterministic heuristic fallback, used on timeout, error or when no
   API key is configured.
5. **Persist** resolved fields with sources and reasoning; mark the job `succeeded`.

## Job lifecycle

`queued → running → succeeded | failed`. A worker picks the job, increments `attempts`, and
retries the whole job up to `MAX_JOB_ATTEMPTS` on unexpected errors. Source failures are not
job failures: they are recorded in the reasoning trace and the job still succeeds.

## Data model

- `contacts`: id, full_name, company, email, domain, created_at, updated_at.
- `enrichment_jobs`: id, contact_id, status, attempts, error, created/started/finished.
- `contact_fields`: contact_id, field, value, confidence, conflict, sources (JSON),
  reasoning, job_id, resolved_at. One current row per (contact, field); history kept.

## Risks and tradeoffs

- **LLM cost and latency**: only call the verifier for fields below the confidence
  threshold, never for every field.
- **Score calibration**: reliabilities are config, not learned. Good enough for v1; revisit
  once there is labelled feedback.
- **Cache staleness**: TTL bounds it; job changes (e.g. title) are the main risk.

## Stack

Python 3.12, FastAPI, Pydantic, SQLAlchemy 2, Alembic, Taskiq (Redis broker),
PostgreSQL, Redis, Docker Compose.
