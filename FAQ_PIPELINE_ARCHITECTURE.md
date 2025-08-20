# Datatalks.club — dlt **S3 → Process → Qdrant** (Daily) with Built‑in LLM Question Classifier & PII Redaction

**Repo:** `spa-raj/dtc-llm-slack-faq-enhancer`  
**Purpose:** Minimal, production‑lean MVP that reads raw Slack JSON from S3, processes **only the last 1 day** of data, classifies questions **via an LLM for all messages**, scrubs PII, embeds, and **upserts** into Qdrant. No Parquet lake is required for this MVP.

---

## Why this revision
We are simplifying the previous “dlt → bronze Parquet → separate classifier → gold Parquet” design into a *single dlt pipeline* that:
1) streams raw Slack export JSON from S3, 2) filters to the most recent day, 3) **redacts PII before any model calls**, 4) calls an LLM to classify **question vs. not**, 5) embeds, and 6) writes to **Qdrant** for retrieval and future FAQ generation.

This reduces moving parts, removes the intermediate lake for MVP, and focuses effort on getting reliable Q→A search running fast.

---

## High‑level flow

```
S3 (raw Slack JSON by course/day)
            │
            ▼
        dlt pipeline
   ┌────────────────────┬───────────────────────────────────────────────────────────────────────┐
   │ Extract            │ Find only yesterday/today partitions (configurable). Read Slack JSON. │
   ├────────────────────┼───────────────────────────────────────────────────────────────────────┤
   │ Transform          │ Normalize + de‑dupe → identify thread head (ts == thread_ts).         │
   │                    │ PII scrub (names, emails, phones, Slack handles, URLs, file links).   │
   │                    │ Call LLM → label “is_question” for **all** candidate messages.        │
   │                    │ For is_question=True: collect thread replies (same day), compact text │
   │                    │ Create embeddings (question + concatenated replies).                   │
   ├────────────────────┼───────────────────────────────────────────────────────────────────────┤
   │ Load               │ Upsert to Qdrant (collection: faq_items).                              │
   └────────────────────┴───────────────────────────────────────────────────────────────────────┘
```

Notes:
- Threads spanning multiple days are handled via **idempotent upserts** using the `thread_ts` as the stable key. Later replies are appended on subsequent daily runs.
- You can switch the “last 1 day” window to “N hours” by changing a single parameter.

---

## Components

### Sources
Raw Slack exports in S3 with Hive‑like partitioning:  
`s3://<DATA_BUCKET>/raw/slack/<course_id>/year=YYYY/month=MM/day=DD/<YYYY-MM-DD>.json`

### dlt pipeline (single job)
- Iterates only the latest day’s prefix per course.
- Normalizes Slack messages, identifies **thread heads** and **replies**.
- Runs **PII scrub** before any model/embedding call.
- Calls **LLM** to classify “is_question” for all thread heads and, if needed, single messages that look like questions.
- Embeds question text and an **answer summary** (concatenated replies or first TA/instructor answer if detectable).
- **Upserts** the record into Qdrant.

### Qdrant (destination)
One collection to start: `faq_items`.

**Point id:** `course_id:thread_ts`  
**Vector:** embedding of `question_text_redacted` (768‑dim default if using MiniLM; configurable).  
**Payload (recommended fields):**
- `course_id` (str)
- `thread_ts` (str)
- `ts` (str, ISO)
- `question_text_redacted` (str)
- `original_question_sha256` (str) – for de‑dupe
- `is_question` (bool)
- `llm_model` (str), `llm_confidence` (float)
- `reply_count` (int)
- `answers_redacted` (list[str]) – compacted reply texts for same day
- `answer_compact_redacted` (str) – short summary/concatenation
- `user_hash` (str|None) – salted HMAC of Slack user id
- `created_at` / `updated_at` (ISO)
- `embed_model` (str), `embed_dim` (int), `embed_version` (str)

Later you may add a second collection for raw messages or for **answers** specifically; not needed for MVP.

---

## PII & Security (MVP‑ready)

**Before any LLM or embedding call:**
- Replace emails with `[EMAIL]`, phone numbers with `[PHONE]`, Slack handles `<@U…>` with `[USER]`, channel links `<#C…>` with `[CHANNEL]`, ordinary URLs with `[URL]`.
- Remove file/private URLs from payloads.
- Hash `user_id` with a **salted HMAC** and keep the salt in a secret store.
- Strip code blocks from PII redaction (preserve code) via simple fence detection (```…```).

**Secrets & IAM**
- Read Slack token, LLM key, and Qdrant API key from environment/CI secrets.
- Use least‑privilege OIDC roles for GitHub Actions and **S3 block public access**. (KMS optional.)

**Transport & storage**
- Use HTTPS for model and Qdrant calls.
- Enable TLS and auth on Qdrant (or use Qdrant Cloud).

**Logging**
- Never log raw message text; log only hashes, counts, and per‑course metrics.

---

## Scheduling & windowing

- Default window is **last 1 day** per course. Build the S3 prefix from `year/month/day` for UTC or course‑local time, as agreed.
- Maintain a tiny **watermark** in dlt state so re‑runs are idempotent. If a file is reprocessed, the Qdrant upsert overwrites by `thread_ts` id.
- CRON: run every morning for the previous day, or hourly with a rolling 24h window.

---

## Minimal data model (JSON)

```json
{
  "id": "ml-zoomcamp:1723632000.000000",
  "vector": [ ... ],
  "payload": {
    "course_id": "ml-zoomcamp",
    "thread_ts": "1723632000.000000",
    "ts": "2025-08-18T07:15:42Z",
    "question_text_redacted": "How do I configure ... ?",
    "original_question_sha256": "c5b2...",
    "is_question": true,
    "llm_model": "gpt-4o-mini",
    "llm_confidence": 0.86,
    "reply_count": 4,
    "answers_redacted": ["Try setting ...", "Docs say ..."],
    "answer_compact_redacted": "Set X in config; refer to link Y.",
    "user_hash": "u:7f2c...",
    "created_at": "2025-08-19T02:00:00Z",
    "updated_at": "2025-08-19T02:00:05Z",
    "embed_model": "all-MiniLM-L6-v2",
    "embed_dim": 384,
    "embed_version": "v1"
  }
}
```

---

## Example dlt sketch (pseudocode)

```python
@dlt.resource(name="slack_messages_daily")
def read_daily(prefix:str, course_id:str, since_date:date):
    # iterate only year=YYYY/month=MM/day=DD under prefix
    for jpath in find_partition_paths(prefix, since_date):
        for msg in load_json_lines(jpath):
            yield normalize(msg, course_id, jpath)

@dlt.transformer
def redact_and_label(rows):
    for r in rows:
        r["text_redacted"] = scrub_pii(r["text"])
        if is_thread_head(r):
            decision, conf, model = llm_is_question(r["text_redacted"])
            r["is_question"] = decision
            r["llm_confidence"] = conf
            r["llm_model"] = model
        yield r

@dlt.resource
def to_qdrant(rows):
    for r in rows:
        if r.get("is_question"):
            q_vec = embed(r["text_redacted"])
            payload = build_payload(r)
            qdrant.upsert(id=f"{r['course_id']}:{r['thread_ts_raw']}", vector=q_vec, payload=payload)
```

Run via `uv run ingest-daily --date=YYYY-MM-DD` in CI.

---

## Operational notes

- If daily volume is large, add a **pre‑filter** (regex for `?` or WH‑words) to cut LLM calls while still honoring your “LLM for all messages” goal for MVP later.
- If a question head appears but replies are missing the same day, the next run will upsert and add the new replies via the same `id`—no duplicates.
- Keep per‑course concurrency low to respect rate limits; exponential backoff on LLM/Qdrant errors.

---

## Extensibility (post‑MVP)
- Add a **canonicalization** step to group similar questions with semantic clustering and store a canonical FAQ entry.
- Replace daily window with an **event‑driven** Slack API poller once the MVP is validated.
- Swap embedding model as needed; store `embed_version` in payload for safe re‑indexing.

---

## Configuration knobs

- `DATA_BUCKET`, `COURSES_YAML`, `WINDOW_DAYS` (default: 1), `QDRANT_URL`, `QDRANT_API_KEY`, `EMBED_MODEL`, `LLM_MODEL`, `PII_SALT`.
- Fallback to local Qdrant (Docker) for dev; use Qdrant Cloud in prod.

---

*Last updated: 2025-08-19 04:06:58Z*
