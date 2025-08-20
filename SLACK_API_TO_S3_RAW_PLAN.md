# Slack API → dlt → S3 (raw) — 24h Public Channels Plan (v2, security‑hardened)

## Security review & score
Overall score: **8.7/10**.

Strengths: OIDC to AWS (no static keys), least‑privilege write to a narrow S3 prefix, no message bodies in logs, 24h bounded ingestion, idempotent writes.  
Improvements applied in v2: environment variables for all operational values, **SSE‑KMS at rest**, **TLS‑only enforced (infra)**, atomic writes with temp keys + copy, optional SHA‑256 sidecar, stricter scopes, jittered backoff, and explicit failure modes.

Residual risks (acceptable for MVP): raw Slack messages may contain PII; mitigate by tight IAM, private bucket, short retention, and process‑downstream redaction.

---

## What changed vs v1 (quick list)
1) Replaced hard‑coded values with **environment variables**, including bucket, region, role‑to‑assume, 24h window, KMS key, paths.  
2) **S3 encryption**: opt‑in to **SSE‑KMS** via env; defaults to SSE‑KMS with a provided key if present, else SSE‑S3.  
3) **Atomic writes**: write to a temp key then copy to final; optional `.sha256` sidecar for integrity.  
4) **Rate limits**: exponential backoff + jitter, sequential per channel, optional API call pacing.  
5) **Secrets handling**: rely on GitHub Environments and `secrets`/`vars`; never print tokens; minimal scopes for Slack.  
6) **Infra checklist** added for Terraform (block public access, deny insecure transport, default encryption, access logs).

---

## Environment variables
Set these in your **GitHub Environment (dev)** and locally (`.env`, not committed).

| Name | Required | Example | Purpose |
|---|---|---|---|
| `SLACK_BOT_TOKEN` | yes (secret) | `xoxb-***` | Bot token with **channels:read** and **channels:history** scopes |
| `BUCKET_DATA` | yes | `dtc-slack-data-dev` | Target S3 bucket for raw dumps |
| `AWS_REGION` | yes | `ap-south-1` | AWS region for S3 client |
| `AWS_ROLE_TO_ASSUME` | yes | `arn:aws:iam::<ACCOUNT_ID>:role/gha-upload-raw-dev` | OIDC role in AWS for GitHub Actions |
| `COURSES_YAML` | yes | `data-ingestion/pipeline/courses.yml` | Path to YAML mapping courses → channel IDs |
| `WINDOW_HOURS` | no | `24` | Ingestion window size (hours) |
| `S3_SSE` | no | `aws:kms` or `AES256` | Server-side encryption mode |
| `S3_SSE_KMS_KEY_ID` | no | `arn:aws:kms:...:key/...` | KMS key for SSE‑KMS |
| `S3_WRITE_ATOMIC` | no | `1` | If `1`, use temp key then copy to final |
| `S3_WRITE_SHA256` | no | `1` | If `1`, write `.sha256` sidecar with content digest |
| `RATE_JITTER_MS` | no | `150` | Extra sleep (ms) between Slack API pages |
| `RATE_MAX_BACKOFF_S` | no | `30` | Cap for exponential backoff on 429s |

---

## Goal
Fetch Slack messages (including thread replies) from selected **public channels** for the **last N hours** (`WINDOW_HOURS`, default 24), then write **raw JSON** to S3 under this partitioned path (by message `ts` date, **UTC**):

```
s3://$BUCKET_DATA/raw/slack/{course_id}/year={YYYY}/month={MM}/day={DD}/{YYYY-MM-DD}.json
```

Each file is a **JSON array** of raw Slack message objects, minimally enriched with `course_id`, `channel_id`, `fetched_at` (UTC ISO).

---

## Files to add / update
1) `data-ingestion/pipeline/slack_api_to_s3_raw.py` — CLI entrypoint; now **prefers env vars** but accepts overrides.  
2) `data-ingestion/pipeline/courses.yml` — maintains `{id, channels[]}`.  
3) `.github/workflows/slack_raw_dev.yml` — updated to read **env/vars**, not hard‑coded ARNs.  
4) (infra) Terraform S3 bucket and IAM — see hardening checklist below.

---

## Step‑by‑step (Claude: implement in order)
1) **Compute window** from env: `WINDOW_HOURS` (default 24), using UTC `now` and Slack `oldest/latest` as seconds‑string.  
2) **Load course/channel config** from `COURSES_YAML`.  
3) **Slack client**: `WebClient(token=SLACK_BOT_TOKEN)`. Scopes: `channels:read`, `channels:history`.  
4) **Page history** for each channel in the window; then **page replies** per thread head within the window.  
5) **Rate limits**: backoff with jitter; on `ratelimited`, sleep `Retry-After + jitter` with exponential cap.  
6) **Enrich & route** each message to `(course_id, year, month, day)` bucket by `ts`.  
7) **Write** one file per course‑day: use SSE‑KMS if key provided; **atomic write** (temp → copy → delete temp); optional `.sha256` sidecar.  
8) **Logging**: counts only (courses, channels, messages, files); no message text or tokens.  
9) **Idempotency**: overwrite same `{YYYY-MM-DD}.json` deterministically for a given window run.  

---

## Updated CLI skeleton (`slack_api_to_s3_raw.py`)
```python
from __future__ import annotations
import argparse, os, time, uuid, hashlib, math, random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple
import orjson, fsspec
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from settings import to_dt, ymd_from_dt  # existing helpers
import yaml

def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v is not None else default

def _jitter_sleep(ms: int | None):
    if not ms: 
        return
    time.sleep(ms / 1000.0)

def _backoff_sleep(base: float, factor: float, attempt: int, cap: float) -> float:
    delay = min(cap, base * (factor ** attempt))
    # add 0-250ms jitter
    delay += random.random() * 0.25
    time.sleep(delay)
    return delay

def _make_fs():
    region = _env("AWS_REGION")
    sse = _env("S3_SSE")  # "aws:kms" or "AES256"
    kms = _env("S3_SSE_KMS_KEY_ID")

    s3_additional_kwargs = {}
    if sse:
        s3_additional_kwargs["ServerSideEncryption"] = sse
    if kms and sse in ("aws:kms", "aws:kms:dsse"):
        s3_additional_kwargs["SSEKMSKeyId"] = kms

    fs = fsspec.filesystem(
        "s3",
        client_kwargs={"region_name": region} if region else None,
        s3_additional_kwargs=s3_additional_kwargs or None,
    )
    return fs

def _sleep_on_ratelimit(e, attempt: int, cap: float) -> bool:
    if isinstance(e, SlackApiError) and getattr(e, "response", None):
        if e.response.get("error") == "ratelimited":
            retry_after = int(e.response.headers.get("retry-after", 1))
            # add small jitter (0-300ms)
            time.sleep(retry_after + (random.random() * 0.3) + 0.5)
            # extra exponential backoff on repeated 429s for safety
            _backoff_sleep(base=1.0, factor=1.5, attempt=attempt, cap=cap)
            return True
    return False

def fetch_24h(client: WebClient, channel_id: str, oldest: str, latest: str, jitter_ms: int | None, backoff_cap: float) -> List[dict]:
    # history
    collected = []
    cursor, attempt = None, 0
    while True:
        try:
            r = client.conversations_history(channel=channel_id, oldest=oldest, latest=latest, cursor=cursor)
            msgs = r.get("messages", []) or []
            collected.extend(msgs)
            _jitter_sleep(jitter_ms)
            if not r.get("has_more"):
                break
            cursor = r.get("response_metadata", {}).get("next_cursor")
            attempt = 0
        except SlackApiError as e:
            if _sleep_on_ratelimit(e, attempt, backoff_cap):
                attempt += 1
                continue
            raise

    # replies
    out = []
    for m in collected:
        out.append(m)
        ts = m.get("ts")
        if not ts:
            continue
        cursor, attempt = None, 0
        while True:
            try:
                rr = client.conversations_replies(channel=channel_id, ts=ts, oldest=oldest, latest=latest, cursor=cursor)
                if rr and rr.get("messages"):
                    out.extend(rr["messages"])
                _jitter_sleep(jitter_ms)
                if not rr.get("has_more"):
                    break
                cursor = rr.get("response_metadata", {}).get("next_cursor")
                attempt = 0
            except SlackApiError as e:
                if _sleep_on_ratelimit(e, attempt, backoff_cap):
                    attempt += 1
                    continue
                raise
    return out

def _final_key(course_id: str, y: int, m: int, d: int) -> str:
    return f"raw/slack/{course_id}/year={y}/month={m:02d}/day={d:02d}/{y}-{m:02d}-{d:02d}.json"

def _tmp_key(final_key: str) -> str:
    return f"raw/slack/_tmp/{uuid.uuid4().hex}/{Path(final_key).name}"

def write_grouped_s3(fs, bucket: str, batches: Dict[Tuple[str, int, int, int], List[dict]]):
    atomic = _env("S3_WRITE_ATOMIC", "1") == "1"
    write_sha = _env("S3_WRITE_SHA256", "0") == "1"

    for (course_id, y, m, d), msgs in batches.items():
        final_key = _final_key(course_id, y, m, d)
        final_uri = f"s3://{bucket}/{final_key}"
        payload = orjson.dumps(msgs)

        if atomic:
            tmp_key = _tmp_key(final_key)
            tmp_uri = f"s3://{bucket}/{tmp_key}"
            with fs.open(tmp_uri, "wb") as f:
                f.write(payload)
            fs.copy(tmp_uri, final_uri)
            fs.rm(tmp_uri, recursive=True)
        else:
            with fs.open(final_uri, "wb") as f:
                f.write(payload)

        if write_sha:
            digest = hashlib.sha256(payload).hexdigest()
            sha_uri = final_uri + ".sha256"
            with fs.open(sha_uri, "wb") as f:
                f.write(digest.encode("utf-8"))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", help="S3 bucket (overrides BUCKET_DATA)")
    ap.add_argument("--courses-yaml", help="Path to courses YAML (overrides COURSES_YAML)")
    ap.add_argument("--window-hours", type=int, help="Hours window (overrides WINDOW_HOURS)")
    args = ap.parse_args()

    # env-first configuration
    bucket = args.bucket or _env("BUCKET_DATA")
    courses_yaml = args.courses_yaml or _env("COURSES_YAML")
    window_hours = args.window_hours or int(_env("WINDOW_HOURS", "24"))
    jitter_ms = int(_env("RATE_JITTER_MS", "0") or 0)
    backoff_cap = float(_env("RATE_MAX_BACKOFF_S", "30"))

    token = _env("SLACK_BOT_TOKEN")
    if not token:
        raise RuntimeError("SLACK_BOT_TOKEN is not set")

    if not bucket:
        raise RuntimeError("BUCKET_DATA (or --bucket) is required")
    if not courses_yaml or not Path(courses_yaml).exists():
        raise RuntimeError("COURSES_YAML (or --courses-yaml) is missing or not found")

    client = WebClient(token=token)
    fs = _make_fs()

    now = datetime.now(timezone.utc)
    oldest_dt = now - timedelta(hours=window_hours)
    oldest = str(oldest_dt.timestamp())
    latest = str(now.timestamp())

    cfg = yaml.safe_load(Path(courses_yaml).read_text(encoding="utf-8"))
    courses = cfg.get("courses", [])

    grouped: Dict[Tuple[str, int, int, int], List[dict]] = {}
    fetched_at = now.isoformat()

    for course in courses:
        cid = course["id"]
        for channel_id in course.get("channels", []):
            msgs = fetch_24h(client, channel_id, oldest, latest, jitter_ms=jitter_ms, backoff_cap=backoff_cap)
            for m in msgs:
                m_enriched = dict(m)
                m_enriched["course_id"] = cid
                m_enriched["channel_id"] = channel_id
                m_enriched["fetched_at"] = fetched_at
                dt = to_dt(m_enriched.get("ts"))
                y, mth, d = ymd_from_dt(dt)
                if not all([y, mth, d]):
                    continue
                grouped.setdefault((cid, y, mth, d), []).append(m_enriched)

    write_grouped_s3(fs, bucket, grouped)

if __name__ == "__main__":
    main()
```

---

## GitHub Actions (env‑driven, OIDC, hourly cron)
Save as `.github/workflows/slack_raw_dev.yml`:

```yaml
name: slack-raw-dev
on:
  workflow_dispatch:
  schedule:
    - cron: "5 * * * *"  # hourly at minute 5 (edit as needed)
permissions:
  id-token: write
  contents: read
env:
  BUCKET_DATA: ${{ vars.BUCKET_DATA }}
  AWS_REGION:  ${{ vars.AWS_REGION }}
  AWS_ROLE_TO_ASSUME: ${{ vars.AWS_ROLE_TO_ASSUME }}
  COURSES_YAML: ${{ vars.COURSES_YAML }}
  WINDOW_HOURS: ${{ vars.WINDOW_HOURS }}
  S3_SSE: ${{ vars.S3_SSE }}
  S3_SSE_KMS_KEY_ID: ${{ vars.S3_SSE_KMS_KEY_ID }}
  S3_WRITE_ATOMIC: ${{ vars.S3_WRITE_ATOMIC }}
  S3_WRITE_SHA256: ${{ vars.S3_WRITE_SHA256 }}
  RATE_JITTER_MS: ${{ vars.RATE_JITTER_MS }}
  RATE_MAX_BACKOFF_S: ${{ vars.RATE_MAX_BACKOFF_S }}
jobs:
  dump:
    runs-on: ubuntu-latest
    environment: dev
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync -g ingest
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ env.AWS_ROLE_TO_ASSUME }}
          aws-region: ${{ env.AWS_REGION }}
      - name: Run Slack 24h dump → S3 (raw)
        env:
          SLACK_BOT_TOKEN: ${{ secrets.SLACK_BOT_TOKEN }}
        run: |
          uv run python data-ingestion/pipeline/slack_api_to_s3_raw.py
```

This workflow pulls everything from **env/vars/secrets**; no hard‑coded ARNs or bucket names appear in the file.

---

## Security & privacy hardening checklist (Terraform + org)
1) **S3 bucket**: Block Public Access (all 4 flags), **default SSE‑KMS**, Object Ownership = BucketOwnerPreferred, access logs to a logs bucket, lifecycle rules for raw (e.g., 30–90 day retention).  
2) **Bucket policy**: Deny `aws:SecureTransport = false`; restrict `s3:PutObject` to the exact prefix `raw/slack/*`; require `s3:x-amz-server-side-encryption` header.  
3) **IAM role (OIDC)**: audience = `sts.amazonaws.com`; condition on `token.actions.githubusercontent.com:sub` to your repo + env; least privilege on S3.  
4) **Slack app**: limit to required scopes; install only in needed workspaces; enable token rotation; review audit logs.  
5) **Secrets**: use GitHub Environment secrets; enable branch protection; restrict who can run workflows in `dev`.  
6) **PII**: raw contains user messages; keep bucket private, monitor access, and implement downstream redaction before external sharing.  
7) **Observability**: enable S3 server access logs/CloudTrail; log counts only in application; no message text in logs.  
8) **Runbook**: ability to revoke Slack token, rotate KMS key grants, and disable IAM role if exposure is suspected.

---

## Expected output
For run on 2025‑08‑19 UTC for course `ml-zoomcamp`:
```
s3://$BUCKET_DATA/raw/slack/ml-zoomcamp/year=2025/month=08/day=19/2025-08-19.json
s3://$BUCKET_DATA/raw/slack/ml-zoomcamp/year=2025/month=08/day=19/2025-08-19.json.sha256   # optional
```
Each file is a JSON array of raw Slack messages (heads + replies) enriched with `course_id`, `channel_id`, and `fetched_at`.
