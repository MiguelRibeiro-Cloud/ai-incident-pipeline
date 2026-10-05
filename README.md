# AI Incident Processing Pipeline

A deliberately small distributed incident-analysis system built to make asynchronous reliability
patterns visible. FastAPI turns a request into a durable PostgreSQL job; Celery then coordinates
deterministic preparation, parallel Gemini analysis, and final fan-in while a React frontend shows
the workflow and its durable execution history live.

Celery is central rather than incidental: the pipeline uses a chain for ordered preparation, a
dynamic group for parallel per-service work, and a chord callback for final synthesis. Retries,
late acknowledgement, worker-loss redelivery, and idempotent writes demonstrate how the workflow
recovers without claiming exactly-once execution.

```text
request → durable job → Redis → Celery chain → parallel group → Gemini
        → chord fan-in → final synthesis → PostgreSQL

transient failure → retry/backoff → recovery
worker loss       → redelivery → idempotent state
```

Technology: Python 3.13, FastAPI, Celery, Redis, PostgreSQL, SQLAlchemy/Alembic, Gemini structured
output, React, TypeScript, Vite, and TanStack Query.

```text
React / Vite browser client
   │ POST job, then poll job + durable execution events
   ▼
FastAPI
   │
   ├──────────────► PostgreSQL (durable job/input/result state)
   │
   ▼
Redis broker
   │
   ▼
normalize (20%)
   │
   ▼
summarize (35%)
   │
   ▼
Celery group (40%)
 ┌─┼──────────────┐
 ▼ ▼              ▼
AI AI             AI       one analyze_service task per distinct service
 └─┼──────────────┘
   ▼
Redis result backend       transient chord coordination and task results
   │
   ▼
chord callback (85%)
   │
   ▼
final AI synthesis (retryable)
   │
   ▼
PostgreSQL (100%, COMPLETED)

Transient AI failure ──► Celery retry (backoff + jitter) ──► same logical work
Worker disappears ─────► unacknowledged broker message ───► redelivery
                                  │
                                  ▼
                  idempotent service rows + durable events
```

The worker messages remain small: tasks receive a job UUID and, for service analysis, a service
name. Each worker loads the normalized incident from PostgreSQL rather than sending the full
incident through Redis.

## Group, chord, and durable state

A Celery `group` runs its signatures independently and can execute them in parallel. The pipeline
dynamically creates one immutable `analyze_service(job_id, service)` signature for every distinct
service in the deterministic summary. A one-service incident is still a valid one-item group.

A Celery `chord` runs a group and invokes its callback only after every header task succeeds. Here,
`synthesize_incident_report` receives the validated service analyses and performs the final Gemini
synthesis. A small bound orchestration task uses Celery's `replace()` to insert this dynamic chord
after normalization and summarization.

Redis now has two transient Celery roles:

- database 0 is the broker for task messages;
- database 1 is the result backend used to coordinate the chord and pass its small results.

This does **not** make Redis the application's result store. The API reads status, progress,
deterministic summaries, service analyses, errors, final reports, and execution events only from
PostgreSQL. Each service worker writes its own row with a database-enforced unique key of
`(job_id, service)`; the chord callback assembles the final stable aggregate.

## Gemini and structured output

The backend uses Google's official `google-genai` Python SDK. Configure both values before
submitting a job:

```text
GEMINI_API_KEY=your-key
GEMINI_MODEL=your-model
ENABLE_CHAOS_DEMO=false
```

Do not commit the key. The API can start without Gemini configuration, but an AI task will fail
cleanly and mark its PostgreSQL job `FAILED` if either setting is absent.

Both service analyses and final reports use Gemini schema-constrained JSON and are validated again
with strict Pydantic models. Confidence is bounded from 0 to 1. Service evidence must match an exact
timestamp/message pair from that service's supplied events; final supporting evidence must match an
original event message. Prompts instruct Gemini to distinguish observations from inference, avoid
inventing context, and describe recommendations only as checks or future actions.

The SDK request uses `response_json_schema` so standard JSON Schema strictness such as
`additionalProperties: false` reaches Gemini unchanged. Pydantic's `minLength` keyword is omitted
only from the provider schema because it is outside the SDK's documented supported subset; the
unchanged Pydantic models still enforce non-empty strings when validating every response.

## Prerequisites and setup

- Python 3.11, 3.12, or 3.13
- Node.js 20.19+ or 22.12+
- Docker with Docker Compose
- a Gemini API key and model for a real analysis

From the repository root:

```bash
cp .env.example .env
# Set GEMINI_API_KEY and GEMINI_MODEL in .env.
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e './backend[dev]'
docker compose up -d --wait
cd backend
python -m app.migrate
alembic check
```

FastAPI, Celery, and Alembic all use the same typed settings layer. It resolves the repository-root
`.env` from the backend module location, so commands launched from `backend/` need no manual
`source` or export step. Real process environment variables take precedence over `.env`, which in
turn takes precedence over safe local defaults. Credential-bearing settings are redacted from the
settings representation. Vite configuration remains separate and only exposes `VITE_` variables.

`REDIS_URL` is the normal Redis configuration for both local and deployed environments. It defaults
to `redis://localhost:6379`; the settings layer derives logical database 0 for the Celery broker and
database 1 for the Celery result backend while preserving the URL's credentials, host, port, scheme,
and query parameters. Set the platform-provided connection URL directly in deployment—for example,
Railway can use `REDIS_URL=${{Redis.REDIS_URL}}`. `CELERY_BROKER_URL` and
`CELERY_RESULT_BACKEND` remain optional independent overrides for advanced configurations and take
precedence over their respective derived URLs.

`backend/uv.lock` is the canonical reproducible backend dependency lock used by Railway/Railpack.
It is generated from `backend/pyproject.toml` for Python 3.13 without replacing the existing local
virtual-environment workflow. To reproduce the locked runtime environment directly with uv:

```bash
cd backend
uv sync --locked --no-dev --python 3.13
```

When declared backend dependencies intentionally change, refresh the lock from `backend/` with
`uv lock --python 3.13` and commit both files together.

## Deployment commands

Run migrations as a pre-deploy step from the backend application environment:

```bash
python -m app.migrate
```

Start the API with the platform-provided port:

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

The application-owned migration module resolves `alembic.ini` from its own filesystem location and
uses Alembic's Python API. It therefore does not depend on the Alembic console script being on
`PATH`, the current working directory, virtual-environment activation tricks, or provider-specific
filesystem paths. The shared settings layer continues to supply `DATABASE_URL`.

The API permits only the configured browser origins. The development defaults are
`http://localhost:5173` and `http://127.0.0.1:5173`; set the comma-separated `CORS_ORIGINS`
environment variable when using a different trusted origin.

## Frontend development

Install dependencies and configure the API origin:

```bash
cd frontend
npm ci
cp .env.example .env.local
npm run dev
```

`VITE_API_BASE_URL` defaults to `http://localhost:8000`, so copying the example is optional for the
standard local setup. Vite serves the portfolio frontend at `http://localhost:5173`. The browser
submits `POST /api/v1/jobs`, then uses TanStack Query to poll both the job and event endpoints every
second. Polling stops automatically after `COMPLETED` or `FAILED`.

Frontend checks:

```bash
cd frontend
npm run lint
npm test
npm run build
```

## Demonstrate parallel execution locally

Start infrastructure once from the repository root:

```bash
docker compose up -d --wait
```

Terminal 1 — API:

```bash
source .venv/bin/activate
cd backend
uvicorn app.main:app --reload
```

Terminal 2 — worker with explicit process concurrency:

```bash
source .venv/bin/activate
cd backend
celery -A app.celery_app worker --loglevel=INFO --concurrency=4
```

Terminal 3 — submit a three-service incident:

```bash
curl -i -X POST http://localhost:8000/api/v1/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "Checkout failures",
    "environment": "production",
    "events": [
      {
        "timestamp": "2026-10-05T08:01:12Z",
        "source": "monitoring",
        "service": "checkout-api",
        "severity": "ERROR",
        "message": "HTTP 503 rate exceeded threshold"
      },
      {
        "timestamp": "2026-10-05T08:01:47Z",
        "source": "application",
        "service": "payment-service",
        "severity": "ERROR",
        "message": "Upstream checkout-api unavailable"
      },
      {
        "timestamp": "2026-10-05T08:02:05Z",
        "source": "application",
        "service": "authentication-service",
        "severity": "WARNING",
        "message": "Token validation latency exceeded threshold"
      }
    ]
  }'
```

Copy the returned `id` and inspect the PostgreSQL-backed status and result:

```bash
curl http://localhost:8000/api/v1/jobs/JOB_ID
curl http://localhost:8000/api/v1/jobs/JOB_ID/events
```

The worker logs include service-analysis start and completion messages. With concurrency 4, starts
for the three services should appear before every completion, making fan-out visible. After the
chord callback completes, `result` contains `deterministic_summary`, `service_analyses`, and
`incident_report`.

## Reliability and failure behavior

### Retry

A retry is an expected transient application/provider failure. The error classifier translates
Gemini HTTP 429, HTTP 5xx, HTTP 408, connection failures, and timeouts into
`TransientLLMError`. Service analysis and final synthesis use Celery retry semantics with at most
three retries, exponential backoff, positive jitter, and a 30-second delay cap:

```text
Gemini 503 → RETRY_SCHEDULED → wait with backoff/jitter → next attempt → success
```

Gemini HTTP 400/401/403-style client errors, missing configuration, malformed structured output,
Pydantic validation failures, and programming errors are not retried. A transient error does not
mark the job failed while a retry remains; an exhausted retry budget or permanent error does.
Celery keeps a retrying chord header member pending, so final synthesis cannot run early.

### Acknowledgement and redelivery

Acknowledgement tells the broker that a worker safely took responsibility for a message. The two
long-running AI tasks use `acks_late=True` and acknowledge only after successful execution. They
also use Celery 5.6's `reject_on_worker_lost=True`; if a worker process disappears, the unacknowledged
message can become available to another worker. `worker_prefetch_multiplier=1` prevents workers
from reserving batches of long external calls.

**Retry and redelivery are different.** A retry is deliberately scheduled by application code
after a classified transient failure and increments Celery's retry count. A redelivery is the
broker delivering the same unacknowledged message after worker loss; late acknowledgement is not
automatic retry logic. When the broker exposes its redelivery marker, the pipeline records
`TASK_REDELIVERED`.

### Idempotency and actual guarantees

Celery may execute work more than once; state-changing operations must therefore be safe under
repeated execution. The first successful service result wins the unique `(job_id, service)` row,
re-execution reuses it, terminal jobs never move backward, conditional finalization prevents a
second callback from overwriting a completed job, and dedupe keys prevent duplicate logical
completion events.

This is **at-least-once style failure behavior**, not magical exactly-once execution. A Gemini
request may be repeated if a worker dies after Gemini processed it but before local completion.
Database idempotency protects application state; it cannot guarantee that an external provider was
called exactly once.

### Durable execution history and polling API

`job_execution_events` stores chronological, independently insertable worker events including task
starts, AI request starts, injected failures, scheduled retries, redeliveries, successes, terminal
failures, synthesis, and completion. `GET /api/v1/jobs/{job_id}/events` returns them ordered by
`created_at` and `id`. The ordinary job endpoints additionally expose current progress,
`deterministic_summary`, all currently persisted `service_analyses`, the final report, and sanitized
failure information. The frontend polls these endpoints with TanStack Query; the system
intentionally adds no SSE or WebSockets.

## Deterministic chaos demo

Chaos mode is rejected unless `ENABLE_CHAOS_DEMO=true`. It is limited to one named incident service
and no more than two injected failures. Each injected failure happens before Gemini is called and
raises the same `TransientLLMError` used by real temporary provider failures, exercising the actual
Celery retry path without consuming quota for failed attempts.

Submit an incident with this additional top-level object:

```json
"chaos": {
  "enabled": true,
  "fail_service": "checkout-api",
  "fail_attempts": 2
}
```

The event API will show two `CHAOS_FAILURE_INJECTED` / `RETRY_SCHEDULED` pairs, followed by
`AI_REQUEST_STARTED` and `TASK_SUCCEEDED` on attempt 3. An optional `delay_seconds` value from 1 to
30 holds only the selected demo task before its real AI call, providing a safe window for the
worker-loss experiment below.

## Manual worker-loss/redelivery demonstration

Use two terminals from `backend/`, with chaos demo enabled. Each worker has one prefork child and a
pidfile:

```bash
celery -A app.celery_app worker -l INFO -c 1 -n recovery-a@%h \
  --pidfile=/tmp/incident-recovery-a.pid
celery -A app.celery_app worker -l INFO -c 1 -n recovery-b@%h \
  --pidfile=/tmp/incident-recovery-b.pid
```

Submit a one-service incident with `fail_attempts: 0` and `delay_seconds: 30`. In the worker that
logs `Starting service analysis`, identify its single prefork child and terminate that child (not
the API, Redis, or PostgreSQL):

```bash
WORKER_MAIN_PID=$(cat /tmp/incident-recovery-a.pid)
ps --ppid "$WORKER_MAIN_PID" -o pid,cmd
kill -9 CHILD_PID_FROM_THE_PREVIOUS_COMMAND
```

If worker B received the task instead, use its pidfile. The parent detects the lost child; because
the task was unacknowledged and opts into rejection on worker loss, another worker can receive it.
Verify `TASK_REDELIVERED` (when Redis/Celery supplies the marker), one logical service row, one
`JOB_COMPLETED`, and a completed report through the two polling endpoints. Broker timing can vary,
so allow a short interval for restoration/redelivery.

`reject_on_worker_lost=True` must be used selectively: a task that deterministically crashes its
worker on every delivery can create an endless redelivery loop. The application provides no HTTP
endpoint that kills workers.

## Tests and checks

Tests replace Gemini calls with small validated fakes; they never call the live API.

```bash
cd backend
pytest
ruff check .
ruff format --check .
python -m app.migrate
alembic upgrade head
alembic check
```

The complete suite is validated on Python 3.13. A previously reported TestClient hang was isolated
to a restricted execution sandbox that denied AnyIO's cross-thread event-loop wakeup; it is not
reproduced in an ordinary host runtime. The exact minimal reproduction and validated package
versions are recorded in [the TestClient runtime note](docs/testclient-runtime-note.md).

## Public deployment notes

The Compose file is for local development: PostgreSQL and Redis bind only to loopback and use
deliberately non-secret development defaults. It is not a production deployment definition. For a
public demo, keep chaos mode disabled unless it is being actively demonstrated, configure an
explicit trusted `CORS_ORIGINS` list, supply secrets through the platform environment, and apply
platform-level request throttling and Gemini quota/budget controls. The intentionally unauthenticated
job submission endpoint can otherwise consume provider quota. Use synthetic data only: job inputs
and results are intentionally readable through the public demo API, including the recent-jobs list.

Interactive API documentation is at <http://localhost:8000/docs>; the health check is at
<http://localhost:8000/health>.

Job creation still has the intentionally documented commit-to-broker publication gap. A
transactional outbox and retries belong to a later stage. Stop infrastructure with
`docker compose down`; PostgreSQL data remains in its named volume.
