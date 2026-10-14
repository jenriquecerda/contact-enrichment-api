# Contact Enrichment API

A backend service that researches a contact across several sources, resolves conflicting
answers and returns each field with a **confidence score**, the **sources** behind it and a
short **reasoning trace**. Enrichment runs as an async job so the API stays fast when
sources are slow or flaky.

Design and tradeoffs: [docs/spec.md](docs/spec.md).

## How it works

```
POST /contacts/{id}/enrich ──► enrichment_jobs (queued) ──► Taskiq worker (Redis)
                                                                │
                     ┌──────────────── EnrichmentPipeline ──────┘
                     │
   sources (concurrent, cached in Redis, retried with backoff + jitter)
                     │
   FieldResolver: group by normalized value, score
       1 - Π(1 - reliability × confidence × recency_decay), flag close calls as conflicts
                     │
   Verifier for weak or conflicting fields only:
       LLM (Claude) ──fails/times out/no key──► deterministic heuristics
                     │
   contact_fields: new current values, old values kept as history
```

Reliability choices worth calling out:

- **Failures are contained.** A failing source is recorded in `source_errors`; the job still
  succeeds with the remaining evidence. Only transient errors (timeouts, 429, 5xx) are retried.
- **Idempotent jobs.** Enqueueing reuses an open job for the contact, and the worker ignores
  redeliveries of finished jobs, so at-least-once delivery is safe.
- **Bounded retries.** Each job counts attempts; after `MAX_JOB_ATTEMPTS` it is marked `failed`
  with the last error.
- **The LLM can't invent data.** It may only pick among candidate values, and any error falls
  back to heuristics, so verification never blocks a job.
- **Schema evolves with migrations.** `0002` adds attempts and field history to existing
  tables, backfills rows and enforces one current value per field with a partial unique index.

## Run it

```bash
cp .env.example .env
docker compose up --build        # postgres, redis, migrations, api, worker
```

```bash
curl -X POST localhost:8000/contacts -H 'content-type: application/json' \
  -d '{"full_name": "Ana Lopez", "company": "Acme, Inc.", "domain": "acme.com"}'
curl -X POST localhost:8000/contacts/<id>/enrich
curl localhost:8000/jobs/<job_id>
curl localhost:8000/contacts/<id>
```

Sources are fixture-backed (`app/sources/data/`) so the demo runs offline; real providers
implement the same `Source` protocol (`name`, `cache_key`, `fetch`).

## Develop

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
ruff check .
```

Tests use in-memory SQLite and a stubbed queue; CI also runs the Alembic migrations up and
down against Postgres.

## Layout

| Path | What |
| --- | --- |
| `app/domain/` | Pydantic models, normalization, the field resolver |
| `app/sources/` | Source protocol, fixture sources, email-pattern inference |
| `app/llm/verifier.py` | LLM verifier with deterministic fallback |
| `app/pipeline.py` | Concurrent fetch, cache, retry, resolve, verify |
| `app/services.py` | Job lifecycle and persistence |
| `app/worker.py` | Taskiq broker and task |
| `app/api.py` | FastAPI endpoints |
| `migrations/` | Alembic migrations |

## Built with AI-assisted development

Developed spec-first with Claude Code: the spec in `docs/` came first, each step was
implemented by the agent against tests, then reviewed and adjusted before committing.
