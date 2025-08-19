# Question Classifier — Architecture & Run/Deploy Plan (LangChain + OpenRouter)

**Repo:** `spa-raj/dtc-llm-slack-faq-enhancer`  
**Scope:** A production-lean MVP component that labels Slack messages as **question vs not** through an LLM called via **LangChain** on **OpenRouter**. It plugs into the daily dlt pipeline described in `FAQ_PIPELINE_ARCHITECTURE_v2.md` and honors the privacy contract (text is PII-scrubbed upstream).  
**Audience:** This document is meant for Claude/Code to generate code and workflows; it contains structure and decisions, not code.

---

## 1) Summary decision for MVP

Run the classifier **in‑process** inside the same GitHub Actions job that executes the `S3 → dlt (Transform) → Qdrant` pipeline. No separate “server” is required. This keeps infra small, secrets simple, and aligns with your daily cron window. If we later need a dedicated service, we can lift the same interface into a serverless target.

---

## 2) Run/Deploy options (choose one)

### Option A — In‑process (recommended for MVP)
The classifier runs **inside the dlt Transform stage** during the scheduled GitHub Actions job. Each batch of sanitized messages is sent to the LLM, the row is enriched, then embedded and upserted to Qdrant in the same run.

Pros: zero extra infra, simplest secrets, no cross‑service hops, easy idempotency with the same job.  
Trade‑offs: job wall‑time increases; must respect OpenRouter rate limits.  
When: MVP / hackathon timeline, modest daily volume.

### Option B — AWS Lambda (serverless microservice)
Expose the classifier as a stateless HTTP endpoint via **API Gateway → Lambda**, or trigger via **EventBridge** with SQS buffers.

Pros: natural horizontal scaling, pay‑per‑use, easy to swap models.  
Trade‑offs: cold starts; 15‑minute max runtime per invoke; you must manage retries, DLQ, Secrets Manager, and VPC egress to the public Internet (OpenRouter).  
When: you need multi‑tenant reuse, or other workflows must call the classifier asynchronously.

### Option C — AWS ECS Fargate (scheduled task or service)
Package as a small container app. Run on a **scheduled task** for batch or as a **service** behind an ALB for on‑demand RPC.

Pros: no cold start; longer jobs than Lambda; easy observability.  
Trade‑offs: more infra to define; you pay while tasks run; still need Secrets Manager and IAM wiring.  
When: sustained throughput, long‑running batches, or you want a private service callable by multiple pipelines.

### Option D — GitHub self‑hosted runner or reusable workflow
Keep it in CI, but on a self‑hosted runner (for network control or GPUs) or split into a **reusable workflow** callable by multiple repos/jobs.

Pros: simple control plane and familiar CI ergonomics.  
Trade‑offs: you operate the runner; fewer strict SLAs than AWS managed services.

> Choice for now: **Option A**. Defer B/C until volume or reuse requires a standalone service.

---

## 3) Module layout (paths; doc‑first for codegen)

```
classifier/
  README.md
  CONFIG.md                     # env vars, defaults, rate limits
  prompts/
    system_question.md          # system role/taxonomy/JSON output rules
  interfaces/
    verdict_schema.md           # JSON schema (Pydantic contract)
  service/
    client.md                   # OpenRouter client: base URL, headers, retries
    batching.md                 # batch size, backoff, order preservation
  integration/
    dlt_integration.md          # field mapping to pipeline rows & Qdrant payload
```

Each `.md` file instructs Claude/Code what to generate; mirrored `.py` files will be created by codegen.

---

## 4) API contract (I/O)

**Input per message**  
• `text_redacted` (string, required) — sanitized message text.  
• `course_id`, `thread_ts_raw`, `ts_raw` (strings, required) — identifiers for idempotency & Qdrant keys.  
• `model_tag` (string, optional) — e.g. `openai/gpt-4o-mini@2025-08`.  
• `timeout_s` (int, default 30).

**Output per message — Verdict**  
• `is_question` (bool)  
• `question_type` (`how-to | debug | concept | setup | resource | other`)  
• `confidence` (float 0..1)  
• `title` (≤ 12 words | null)  
• `reason` (one sentence)  
• `llm_model` (string)  
• `latency_ms` (int)  
• `request_id` (string | null)

**Batch**: ordered list in, ordered list out. **Idempotency key**: `sha256(text_redacted) + llm_model` (for in‑run memoization).

---

## 5) Inference flow

1) Preconditions: `text_redacted` produced upstream (no PII).  
2) Build deterministic request: temperature 0, max tokens ~256, structured JSON output.  
3) Call OpenRouter model via LangChain client; attach optional headers for attribution.  
4) Parse to the Verdict schema; clamp `confidence` to [0,1]; record `latency_ms` and `llm_model`.  
5) Batching: chunk to `MAX_BATCH=16`; sequential per course to respect rate limits; small jitter between batches.  
6) Errors: `MAX_RETRIES=3` with exponential backoff; on final failure, emit `is_question=false`, `confidence=0.0`, `reason="llm_error"`, `llm_model="error:<model>"` and continue.

Optional: per‑run memo cache keyed by `(digest(text_redacted), OPENROUTER_MODEL)`.

---

## 6) Config & secrets (GitHub **dev** environment)

Required env:  
`OPENROUTER_API_KEY` (secret), `OPENROUTER_MODEL` (var/secret), `OPENROUTER_BASE_URL=https://openrouter.ai/api/v1`.

Optional env:  
`OPENROUTER_HTTP_REFERER`, `OPENROUTER_X_TITLE`, `LLM_TIMEOUT_S` (default 30), `MAX_BATCH` (default 16), `MAX_RETRIES` (default 3).

Secrets live in the **environment** scope and are only available to jobs running in that environment. Avoid logging response bodies; log counts and timings only.

---

## 7) Integration with dlt (daily window; Qdrant upsert)

Where: the classifier is invoked **inside the Transform stage** described in `FAQ_PIPELINE_ARCHITECTURE_v2.md`. The transformer reads rows with `text`, writes: `is_question`, `llm_confidence`, `llm_model`, `question_title`, `question_type`, `question_reason`.  
When `is_question=true` for a thread head, the pipeline concatenates same‑day replies, embeds, and **upserts** to Qdrant using `id = course_id:thread_ts`.

**Mapping**  
Input: `text_redacted`, `course_id`, `ts_raw`, `thread_ts_raw`.  
Output fields added to row: above `question_*` fields.  
Qdrant payload: extend the v2 payload with the `question_*` fields.

---

## 8) How to run it — per deployment option

### A) In‑process in GitHub Actions (recommended)
1. Ensure `pyproject.toml` lists the classifier deps and a runner script (e.g., `label-daily`) so CI can `uv sync` and run it.  
2. In the **dlt** job: initialize the classifier once, call it in the transform, then proceed to embedding and Qdrant.  
3. Run on the same schedule as ingest. The job environment must be `dev` so it inherits `OPENROUTER_*` env vars.

### B) AWS Lambda via API Gateway
1. Package the classifier as a small handler with JSON input/output using the same Verdict schema.  
2. Use AWS Secrets Manager for `OPENROUTER_*`; grant the Lambda role `secretsmanager:GetSecretValue`.  
3. Add an **EventBridge** rule to kick off classification after ingest, or call the API from the CI job if you want synchronous behavior.  
4. Set reserved concurrency and optionally add SQS as a buffer to smooth spikes.

### C) ECS Fargate (scheduled task)
1. Containerize a tiny HTTP or batch worker that reads from S3 (or receives JSON via HTTP) and emits Verdicts to stdout or S3.  
2. Schedule with EventBridge right after ingest or run as an on‑demand service behind ALB for RPC.  
3. Use Secrets Manager for API keys; task role needs `secretsmanager:GetSecretValue` and S3 access if reading/writing artifacts.

> If you move to B or C later, keep the Verdict contract and prompts identical so the dlt integration stays unchanged.

---

## 9) GitHub Actions wiring (environment **dev**)

- The ingest job already uses `uv sync`/scripts; run the classifier inline within that job or as a subsequent job in the same workflow.  
- Export `OPENROUTER_*` in the job env from environment secrets/vars.  
- Limit concurrency per course; optionally add a matrix strategy per course with `max-parallel: 1` to respect rate limits.

---

## 10) Privacy, observability, and SLOs

Privacy: never send unsanitized text; avoid logging message bodies; store only hashed ids in logs/metrics.  
Observability: counters for processed, retried, failed, and average latency; annotate with `llm_model`.  
SLOs: a daily run must complete within the CI job time limit (e.g., ≤ 60 minutes). If breached, reduce batch size or split the schedule by course.

---

## 11) Testing & rollout

- Unit tests: schema fidelity; error policy; memoization check.  
- Golden set: 20–50 labeled examples to guard against regressions.  
- Dry‑run a single small course‑day first; then turn on the full daily window.  
- Lock the model tag once stable and record it in outputs for reproducibility.

---

## 12) Post‑MVP paths

- Promote to Lambda/ECS if volume or reuse increases.  
- Add a small local classifier (e.g., SetFit) for pre‑filtering with LLM as fallback.  
- Canonicalize similar questions into a single FAQ entry and deduplicate.

---

_Last updated: 2025-08-19 09:48:17Z_
