# Question Classifier — Architecture & Integration Plan (LangChain + OpenRouter)

**Repo:** `spa-raj/dtc-llm-slack-faq-enhancer`  
**Scope:** Production-lean MVP module that labels Slack messages as **question vs not** using an LLM via **LangChain** against **OpenRouter**. Designed to plug into the daily dlt pipeline described in `FAQ_PIPELINE_ARCHITECTURE_v2.md`.  
**Principles:** keep it simple, privacy-first (PII already scrubbed upstream), deterministic, traceable, idempotent.

---

## 1) Goals and non-goals

Goals: a) accept redacted text and return a strict, typed verdict with confidence and a short title; b) support batch inference with backoff and minimal cost controls; c) integrate cleanly inside the dlt transform stage without introducing new storage layers; d) run with GitHub Actions **dev** environment secrets.

Non-goals for MVP: hybrid model, canonicalization, learning-to-rank, and separate gold Parquet. Those can be added post-MVP if needed.

---

## 2) Module layout (paths relative to repo root)

```
classifier/
  README.md
  CONFIG.md
  prompts/
    system_question.md
  interfaces/
    verdict_schema.md          # JSON schema / Pydantic model contract
  service/
    client.md                  # HTTP/headers/model selection, retry policy
    batching.md                # batch size, concurrency, memoization
  integration/
    dlt_integration.md         # exact mapping of outputs → pipeline row fields
```

No code in this document; each `.md` above is an implementation guide for Claude/Code to generate code into mirrored `.py` files with the same names.

---

## 3) API contract (I/O)

Input (per message):  
• `text_redacted` (string, required): message content after PII scrub.  
• `course_id`, `thread_ts_raw`, `ts_raw` (strings, required for id and idempotency).  
• `model_tag` (string, optional): e.g., `openai/gpt-4o-mini@2025-08`.  
• `timeout_s` (int, optional, default 30).

Output (per message): JSON object named **Verdict** with fields:  
• `is_question` (bool).  
• `question_type` (enum) one of `how-to | debug | concept | setup | resource | other`.  
• `confidence` (float 0..1).  
• `title` (string ≤ 12 words, nullable).  
• `reason` (string one sentence).  
• `llm_model` (string).  
• `latency_ms` (int).  
• `request_id` (string; provider request id if available).

Batch API: accepts a list of inputs, returns an ordered list of Verdicts. Must preserve order.

Idempotency key: `sha256(text_redacted) + llm_model`. Use this to optionally memoize results within a single run.

---

## 4) Inference flow (single path, LLM-only as requested)

1. Preconditions: upstream dlt step produced `text_redacted`. PII scrub is **mandatory** before calling this module.  
2. Build request: temperature 0, max tokens ~256, deterministic, JSON schema enforced via LangChain’s structured output.  
3. Call OpenRouter with model `OPENROUTER_MODEL`. Keep base URL `https://openrouter.ai/api/v1`. Add optional headers: `HTTP-Referer`, `X-Title`.  
4. Parse structured response into Verdict. Clamp confidence to [0, 1].  
5. Attach tracing metadata (latency, model name).  
6. For batch calls: chunk to `MAX_BATCH=16` and run sequentially per course to avoid rate spikes.  
7. Error policy: three attempts with exponential backoff (1s, 2s, 4s). On final failure, emit `is_question=false`, `confidence=0.0`, `reason="llm_error"`, and tag `llm_model` with `"error:<model>"`. This keeps the pipeline progressing.

Optional memoization (MVP-friendly): in-process dict keyed by `(digest(text_redacted), OPENROUTER_MODEL)`. Only for the lifetime of the job.

---

## 5) Prompt and schema

System prompt (stored at `classifier/prompts/system_question.md`):  
• Role: strict classifier for Slack course channels.  
• Definition: a question includes explicit interrogatives and implicit help requests (“stuck on… how to…”) even without `?`.  
• Exclusions: greetings, thanks, FYI, status updates, pure dumps without ask.  
• Taxonomy: how-to, debug, concept, setup, resource, other.  
• Title rule: ≤ 12 words if and only if `is_question=true`.  
• Output: **must** return a JSON object matching the Verdict schema.

Schema (stored at `classifier/interfaces/verdict_schema.md`): shows the JSON schema for Verdict so the generated code can wire Pydantic accordingly.

---

## 6) Configuration and secrets

All configuration comes from environment variables with safe defaults. Define them under the GitHub **dev environment** (not repo-wide).

Required:  
• `OPENROUTER_API_KEY` — stored as environment secret in the **dev** environment.  
• `OPENROUTER_MODEL` — e.g., `openai/gpt-4o-mini`.  
• `OPENROUTER_BASE_URL` — default `https://openrouter.ai/api/v1`.

Optional:  
• `OPENROUTER_HTTP_REFERER` — your repo URL for attribution.  
• `OPENROUTER_X_TITLE` — app title for OpenRouter dashboard.  
• `LLM_TIMEOUT_S` (default 30), `MAX_BATCH` (default 16), `MAX_RETRIES` (default 3).

Secrets live in GitHub **environment** scope and are read at runtime by the CI job that runs the daily pipeline. Trust relationship for the `dev` environment exists per the OIDC guide; the classifier runs under that environment with least-privilege AWS access only for reading/writing project data. Keep provider API keys out of logs and artifacts.

---

## 7) Reliability, cost control, and privacy

Reliability: deterministic settings; retries with jitter; graceful degradation (`is_question=false` on failure). Concurrency is limited per course to avoid spikes. Add a small random delay between batches to smooth rate bursts.

Cost control: batch size 16; single pass LLM on **all** candidate messages as per MVP; memoize within run; optional pre-filter flag to be enabled post-MVP if volumes demand it.

Privacy: never send unsanitized text; log only hashes and counters; never persist prompts or raw responses beyond the sanitized Verdict. Preserve code blocks as text; URLs and handles should already be masked upstream.

Observability: emit counters per run — total, success, retries, failures; average latency; model used; top N titles by frequency (sanitized). Avoid logging message bodies.

---

## 8) Integration guide with dlt (daily window, Qdrant payload)

Where: inside the **Transform** stage of the single dlt pipeline documented in `FAQ_PIPELINE_ARCHITECTURE_v2.md`. The transformer receives rows with `text` and writes enriched fields `is_question`, `llm_confidence`, `llm_model`, `question_title`, `question_type`, `question_reason` before the Load step pushes to Qdrant. Use `thread_ts_raw` to maintain stable Qdrant ids `course_id:thread_ts`.

Mapping:  
• Input to classifier: `text_redacted` (from your PII scrub), plus `course_id`, `ts_raw`, `thread_ts_raw`.  
• Output to row: set `row["is_question"]`, `row["llm_confidence"]`, `row["llm_model"]`, `row["question_title"]`, `row["question_type"]`, `row["question_reason"]`.  
• Qdrant payload: keep the fields already listed in the v2 architecture and add the `question_*` fields for downstream FAQ generation.

Execution: initialize the classifier once per process (cold start), then stream batches through it. If the thread head has `is_question=true`, proceed to collect same-day replies and embed before upsert to Qdrant.

Idempotency: re-runs overwrite the same Qdrant point id based on `course_id:thread_ts`. If the same message text is reprocessed, the digest-based memoization avoids refiring the LLM in the same job run.

---

## 9) GitHub Actions integration (dev environment)

Jobs that run the daily ingest should also run the classifier step as part of the same job or as a subsequent step. Ensure the job runs in the **dev** environment so it can access `OPENROUTER_*` secrets. Use `uv sync` to install dependencies declared in `pyproject.toml`, then `uv run` to execute the pipeline entrypoint.

Environment variables in the workflow:  
• `OPENROUTER_API_KEY: ${ secrets.OPENROUTER_API_KEY }`  
• `OPENROUTER_MODEL: ${ vars.OPENROUTER_MODEL }` (or a secret if you prefer)  
• `OPENROUTER_BASE_URL: https://openrouter.ai/api/v1`  
• `OPENROUTER_HTTP_REFERER: https://github.com/spa-raj/dtc-llm-slack-faq-enhancer` (optional)  
• `OPENROUTER_X_TITLE: DTC Slack FAQ Enhancer (MVP)` (optional)

---

## 10) Testing strategy (MVP minimum)

Unit tests: a stubbed LLM client that returns deterministic Verdicts for canned prompts. Validate schema compliance, threshold clamping, and error fallbacks.  
Contract tests: compare a small golden set (20–50 messages) to expected outcomes vetted by a human.  
Load smoke test: one course-day slice run end-to-end in CI with the real model but reduced batch size (e.g., 4).

---

## 11) Rollout plan

Step 1: wire the module in transform and run against a tiny slice (last 2 hours).  
Step 2: enable full **last 1 day** window per course.  
Step 3: monitor counts and override rate for two days; adjust batch size/timeouts if needed.  
Step 4: lock the model tag (`OPENROUTER_MODEL`) and annotate runs with the tag in output fields.

---

## 12) Post‑MVP options (deferred)

Hybrid mode (local SetFit primary, LLM fallback for uncertainty band), canonical question grouping, multilingual handling, cross-day thread reconciliation, and active learning loops. These are intentionally excluded from MVP to stay on schedule.

---

## 13) Acceptance checklist

- Deterministic per-run behavior with schema-validated outputs.  
- No raw PII leaves the process.  
- Daily ingest produces Qdrant points with `is_question=true` on valid thread heads.  
- CI runs in **dev** environment with secrets scoped there.  
- Metrics recorded for volume, failure rate, and latency.

---

_Last updated: 2025-08-19 04:21:41Z_
