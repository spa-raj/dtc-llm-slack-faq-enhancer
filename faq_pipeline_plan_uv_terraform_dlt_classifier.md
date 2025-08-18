# Datatalks.club — Ingestion with **dlt** + Terraform, and a Separate **FAQ Classifier Service** (uv-native)
**Repo:** `spa-raj/dtc-llm-slack-faq-enhancer` (branch: `data-ingestion`)  
Uses **uv** for dependency & environment management (no `pip`).  
Single-channel-per-course. Classification lives *outside* dlt.

> Your repo already contains `pyproject.toml` and `uv.lock` at the root, and a `data-ingestion/` folder. This plan drops files into that layout and adds Terraform infra under `infra/terraform/s3`. 

---

## 0) What goes where (paths relative to repo root)

```
infra/
  terraform/
    s3/
      versions.tf
      provider.tf
      variables.tf
      main.tf
      outputs.tf

data-ingestion/
  pipeline/
    settings.py
    slack_pipeline.py
    courses.yml

classifier/
  __init__.py
  types.py
  prefilter.py
  setfit_model.py
  llm_fallback.py
  hybrid.py
  batch_run.py
  daily_run.py
```

- **dlt** only ingests and normalizes Slack JSON → **bronze Parquet**.  
- **Classifier Service** (separate package) reads bronze and writes **gold** (`faq_labels`, optional canonicalization tables).  
- **Terraform** manages S3 as code (bucket, encryption, lifecycle, optional writer IAM).

---

## 1) uv: environments & dependencies

### 1.1 Add runtime deps to `pyproject.toml`
Use **uv** to record libs in `pyproject.toml` (keeps `uv.lock` in sync):
```bash
# ingestion / data lake
uv add dlt pyarrow s3fs fsspec orjson python-dateutil pyyaml

# classifier (hybrid: SetFit primary + LLM fallback)
uv add setfit datasets sentence-transformers pydantic

# optional: QA & local SQL
uv add duckdb
```

> Use dependency groups, update the 'pyproject.toml' to reflect this:

> ```bash
> uv add --group ingest dlt pyarrow s3fs fsspec orjson python-dateutil pyyaml
> uv add --group classify setfit datasets sentence-transformers pydantic duckdb
> ```

Then install everything:
```bash
uv sync
```

Tip: run commands without activating a venv explicitly:
```bash
uv run python -V
```

### 1.2 `scripts` in `pyproject.toml`
Add convenience scripts so you can run via `uv run <name>`:

```toml
[tool.uv.scripts]
ingest = "python data-ingestion/pipeline/slack_pipeline.py"
label-batch = "python classifier/batch_run.py"
label-daily = "python classifier/daily_run.py"
```

Run:
```bash
uv run ingest
uv run label-batch
uv run label-daily
```

---

## 2) Terraform S3 (managed as code)

Create **`infra/terraform/s3`** with these files:

**`versions.tf`**
```hcl
terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}
```

**`provider.tf`**
```hcl
provider "aws" { region = var.aws_region }
```

**`variables.tf`**
```hcl
variable "aws_region"            { type = string, default = "ap-south-1" }
variable "bucket_name"           { type = string }
variable "use_kms"               { type = bool,   default = false }
variable "kms_key_arn"           { type = string, default = "" }
variable "raw_ia_days"           { type = number, default = 30 }
variable "raw_glacier_days"      { type = number, default = 180 }
variable "bronze_ia_days"        { type = number, default = 30 }
variable "silver_ia_days"        { type = number, default = 30 }
variable "enable_versioning"     { type = bool,   default = true }
variable "tags"                  { type = map(string), default = {} }
variable "create_writer_policy"  { type = bool, default = true }
variable "writer_principal_arn"  { type = string, default = "" }
```

**`main.tf`**
```hcl
resource "aws_s3_bucket" "slack" {
  bucket = var.bucket_name
  tags   = var.tags
}

resource "aws_s3_bucket_public_access_block" "slack" {
  bucket                  = aws_s3_bucket.slack.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "slack" {
  bucket = aws_s3_bucket.slack.id
  rule { object_ownership = "BucketOwnerPreferred" }
}

resource "aws_s3_bucket_versioning" "slack" {
  bucket = aws_s3_bucket.slack.id
  versioning_configuration {
    status = var.enable_versioning ? "Enabled" : "Suspended"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "slack" {
  bucket = aws_s3_bucket.slack.id
  rule { apply_server_side_encryption_by_default {
    sse_algorithm     = var.use_kms ? "aws:kms" : "AES256"
    kms_master_key_id = var.use_kms ? var.kms_key_arn : null
  }}
}

data "aws_iam_policy_document" "deny_insecure_transport" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    principals { type = "*", identifiers = ["*"] }
    resources = [aws_s3_bucket.slack.arn, "${aws_s3_bucket.slack.arn}/*"]
    condition { test = "Bool", variable = "aws:SecureTransport", values = ["false"] }
  }
}

resource "aws_s3_bucket_policy" "slack" {
  bucket = aws_s3_bucket.slack.id
  policy = data.aws_iam_policy_document.deny_insecure_transport.json
}

resource "aws_s3_bucket_lifecycle_configuration" "slack" {
  bucket = aws_s3_bucket.slack.id

  rule {
    id = "raw-transitions"
    status = "Enabled"
    filter { prefix = "raw/slack/" }
    transition { days = var.raw_ia_days      storage_class = "STANDARD_IA" }
    transition { days = var.raw_glacier_days storage_class = "GLACIER" }
  }

  rule {
    id = "bronze-transitions"
    status = "Enabled"
    filter { prefix = "bronze/slack/" }
    transition { days = var.bronze_ia_days storage_class = "STANDARD_IA" }
  }

  rule {
    id = "silver-transitions"
    status = "Enabled"
    filter { prefix = "silver/slack/" }
    transition { days = var.silver_ia_days storage_class = "STANDARD_IA" }
  }
}

data "aws_iam_policy_document" "writer" {
  statement { sid="ListBucket", effect="Allow", actions=["s3:ListBucket"], resources=[aws_s3_bucket.slack.arn] }
  statement { sid="RW",        effect="Allow", actions=["s3:GetObject","s3:PutObject","s3:DeleteObject"], resources=["${aws_s3_bucket.slack.arn}/*"] }
}

resource "aws_iam_policy" "writer" {
  count       = var.create_writer_policy ? 1 : 0
  name        = "${var.bucket_name}-writer"
  description = "RW policy for Slack data lake bucket"
  policy      = data.aws_iam_policy_document.writer.json
}
```

**`outputs.tf`**
```hcl
output "bucket_name"       { value = aws_s3_bucket.slack.bucket }
output "bucket_arn"        { value = aws_s3_bucket.slack.arn }
output "writer_policy_arn" { value = try(aws_iam_policy.writer[0].arn, null) }
```

Apply:
```bash
cd infra/terraform/s3
terraform init
terraform apply -auto-approve -var="bucket_name=dtc-slack-data-prod" -var="aws_region=ap-south-1"
```

---

## 3) S3 path layout (single channel per course)

```
# Raw JSON
s3://dtc-slack-data-prod/raw/slack/{course_id}/year={YYYY}/month={MM}/day={DD}/{YYYY-MM-DD}.json

# Bronze Parquet (from dlt)
s3://dtc-slack-data-prod/bronze/slack/messages/course_id={course_id}/year={YYYY}/month={MM}/day={DD}/part-*.parquet

# Gold Parquet (from Classifier Service)
s3://dtc-slack-data-prod/gold/faq_labels/course_id={course_id}/year={YYYY}/month={MM}/day={DD}/part-*.parquet
```

---

## 4) dlt ingestion (data-ingestion/)

**`data-ingestion/pipeline/settings.py`**
```python
from datetime import datetime, timezone
from dateutil import parser as dateparser
from hashlib import sha256

def to_dt(ts_str: str | None):
    if not ts_str: return None
    try:
        sec = float(ts_str)  # "1723556195.123456"
        return datetime.fromtimestamp(sec, tz=timezone.utc)
    except Exception:
        try:
            return dateparser.parse(ts_str).astimezone(timezone.utc)
        except Exception:
            return None

def ymd_from_dt(dt: datetime | None):
    if not dt: return (None, None, None)
    return dt.year, dt.month, dt.day

def digest(s: str) -> str:
    return sha256(s.encode("utf-8", errors="ignore")).hexdigest()
```

**`data-ingestion/pipeline/slack_pipeline.py`**
```python
from __future__ import annotations
from typing import Iterator, Dict, Any
from pathlib import Path
import dlt, fsspec, orjson
from dlt.common.time import ensure_pendulum_datetime
from .settings import to_dt, ymd_from_dt, digest

def _is_s3(path: str) -> bool: return path.startswith("s3://")

def _iter_json_files(prefix: str):
    if _is_s3(prefix):
        fs = fsspec.filesystem("s3")
        for p in fs.find(prefix):
            if p.endswith(".json"):
                yield f"s3://{p}"
    else:
        for p in Path(prefix).rglob("*.json"):
            yield str(p)

def _path_ymd(path: str):
    year = month = day = None
    parts = path.split("/")
    for seg in parts:
        if seg.startswith("year="):  year  = year  or int(seg.split("=")[1])
        if seg.startswith("month="): month = month or int(seg.split("=")[1])
        if seg.startswith("day="):   day   = day   or int(seg.split("=")[1])
    if not (year and month and day):
        fname = parts[-1]
        if len(fname) >= 15 and fname.endswith(".json"):
            year  = year  or int(fname[0:4])
            month = month or int(fname[5:7])
            day   = day   or int(fname[8:10])
    return year, month, day

def _open_json(path: str):
    if _is_s3(path):
        fs = fsspec.filesystem("s3")
        with fs.open(path, "rb") as f: return orjson.loads(f.read())
    return orjson.loads(Path(path).read_bytes())

@dlt.resource(name="messages", write_disposition="append")
def messages_from_raw(raw_prefix: str, course_id: str) -> Iterator[Dict[str, Any]]:
    """Yield normalized rows for bronze.messages; NO classification logic here."""
    for jpath in _iter_json_files(raw_prefix):
        y, m, d = _path_ymd(jpath)
        try:
            data = _open_json(jpath)
            if not isinstance(data, list): continue
        except Exception as e:
            print("Failed:", jpath, e); continue

        for msg in data:
            if not isinstance(msg, dict): continue
            ts_raw = msg.get("ts")
            t_ts = to_dt(ts_raw)
            thread_ts_raw = msg.get("thread_ts")
            t_thread = to_dt(thread_ts_raw)

            y0, m0, d0 = ymd_from_dt(t_ts)
            year, month, day = (y or y0), (m or m0), (d or d0)

            text = msg.get("text") or ""
            reactions = [{"name": r.get("name"), "count": int(r.get("count") or 0)} for r in (msg.get("reactions") or [])]
            files = [{
                "id": f.get("id"), "name": f.get("name"), "mimetype": f.get("mimetype"),
                "size": int(f.get("size") or 0), "url_private": f.get("url_private")
            } for f in (msg.get("files") or [])]

            yield {
                "course_id": course_id,
                "channel": None,  # single-channel-per-course; keep nullable for compatibility
                "ts": t_ts, "ts_raw": ts_raw,
                "thread_ts": t_thread, "thread_ts_raw": thread_ts_raw,
                "is_thread_head": (ts_raw is not None and ts_raw == thread_ts_raw),
                "user_id": msg.get("user"),
                "client_msg_id": msg.get("client_msg_id"),
                "bot_id": msg.get("bot_id"),
                "subtype": msg.get("subtype"),
                "text": text, "text_plain": text,
                "reactions": reactions, "files": files,
                "reply_count": msg.get("reply_count"),
                "reply_users_count": msg.get("reply_users_count"),
                "latest_reply": to_dt(msg.get("latest_reply")),
                "edited_ts": to_dt(msg.get("edited", {}).get("ts")) if isinstance(msg.get("edited"), dict) else None,
                "deleted": False,
                "ingestion_time": ensure_pendulum_datetime(None),
                "source_file_path": jpath,
                "sha256": digest(text),
                "year": year, "month": month, "day": day,
            }

def run_course(raw_prefix: str, course_id: str):
    pipe = dlt.pipeline(pipeline_name="slack_ingest_v2", destination="filesystem", dataset_name="slack")
    rows = messages_from_raw(raw_prefix=raw_prefix, course_id=course_id)
    info = pipe.run({"messages": rows}, loader_file_format="parquet", write_disposition="append")
    print(info)

def run_all():
    import yaml
    from pathlib import Path
    cfg = yaml.safe_load((Path(__file__).parent / "courses.yml").read_text())
    for c in cfg["courses"]:
        run_course(raw_prefix=c["raw_prefix"], course_id=c["id"])

if __name__ == "__main__":
    run_all()
```

**`data-ingestion/pipeline/courses.yml`**
```yaml
courses:
  - id: ml-zoomcamp
    raw_prefix: "s3://dtc-slack-data-prod/raw/slack/ml-zoomcamp"
  - id: de-zoomcamp
    raw_prefix: "s3://dtc-slack-data-prod/raw/slack/de-zoomcamp"
# Append new courses here
```

Run ingestion:
```bash
# write directly to S3 (set in .dlt/secrets.toml as bucket_url="s3://dtc-slack-data-prod/bronze/slack")
uv run python data-ingestion/pipeline/slack_pipeline.py
```

> `.dlt/config.toml` / `.dlt/secrets.toml` stay at repo root as before; only the pipeline code moved under `data-ingestion/`.

---

## 5) Classifier Service (separate from dlt)

Implements your **hybrid** plan: **SetFit** primary, **LLM** fallback only for the uncertainty band. Produces **gold** Parquet.

**`classifier/types.py`**
```python
from pydantic import BaseModel
from typing import Optional

class LabelRecord(BaseModel):
    course_id: str
    message_id: str
    ts: Optional[str]
    thread_ts: Optional[str]
    is_thread_head: Optional[bool]
    text: Optional[str]
    is_faq: bool
    score: float
    decision_source: str  # "model" | "llm"
    threshold_low: float
    threshold_high: float
    classifier_name: str
    classifier_version: str
    llm_model: Optional[str] = None
    llm_confidence: Optional[float] = None
    canonical_id: Optional[str] = None
    canonical_text: Optional[str] = None
    embedding_model: Optional[str] = None
    embedding_version: Optional[str] = None
    year: int
    month: int
    day: int
```

**`classifier/prefilter.py`**
```python
def is_question_like(text: str) -> bool:
    if not text: return False
    t = text.strip()
    if len(t) < 6 or len(t) > 240: return False
    tl = t.lower()
    return ("?" in t) or tl.startswith(("how ","what ","when ","where ","why ","which ","does ","do ","can ","is ","are ","anyone know"))
```

**`classifier/setfit_model.py`**
```python
from setfit import SetFitModel
import numpy as np

class SetFitWrapper:
    def __init__(self, path_or_hub="sentence-transformers/all-MiniLM-L6-v2"):
        self.model = SetFitModel.from_pretrained(path_or_hub)
        self.name = "setfit-miniLM"
        self.version = "v1"
    def predict_proba(self, texts):
        return np.asarray(self.model.predict_proba(texts)[:,1], dtype=float)
```

**`classifier/llm_fallback.py`**
```python
def ask_llm_is_faq(text: str) -> tuple[bool, float, str]:
    # Integrate GPT/Gemini here with a strict JSON schema & FAQ definition.
    # Return (is_faq, confidence, model_name)
    return (False, 0.0, "llm-stub")
```

**`classifier/hybrid.py`**
```python
import pyarrow as pa, pyarrow.dataset as ds, pyarrow.parquet as pq
import fsspec
from datetime import timezone, datetime
from .prefilter import is_question_like
from .setfit_model import SetFitWrapper
from .llm_fallback import ask_llm_is_faq
from .types import LabelRecord

class HybridClassifier:
    def __init__(self, bucket="dtc-slack-data-prod", bronze_prefix="bronze/slack/messages",
                 gold_prefix="gold/faq_labels", low=0.45, high=0.65):
        self.bucket = bucket
        self.bronze = f"s3://{bucket}/{bronze_prefix}"
        self.gold   = f"s3://{bucket}/{gold_prefix}"
        self.low, self.high = low, high
        self.clf = SetFitWrapper()

    def _read_messages(self, course_id:str, y:int, m:int, d:int):
        path = f"{self.bronze}/course_id={course_id}/year={y}/month={m:02d}/day={d:02d}"
        dataset = ds.dataset(path, format="parquet", filesystem=fsspec.filesystem("s3"))
        return dataset.to_table(columns=[
            "course_id","ts","ts_raw","thread_ts","thread_ts_raw","is_thread_head","text","year","month","day"
        ])

    def _write_labels(self, table: pa.Table, course_id:str, y:int, m:int, d:int):
        out = f"{self.gold}/course_id={course_id}/year={y}/month={m:02d}/day={d:02d}"
        fs = fsspec.filesystem("s3")
        pq.write_to_dataset(table, root_path=out, filesystem=fs, compression="zstd")

    def process_partition(self, course_id:str, y:int, m:int, d:int):
        tab = self._read_messages(course_id, y, m, d)
        df = tab.to_pandas()

        cand = df[(df["is_thread_head"]==True) & (df["text"].astype(str).map(is_question_like))].copy()
        if cand.empty:
            return

        probs = self.clf.predict_proba(cand["text"].tolist())
        recs = []
        for (_, row), p in zip(cand.iterrows(), probs):
            decision_source = "model"
            is_faq = p >= 0.5
            llm_model = None; llm_conf = None

            if self.low <= p <= self.high:
                v, c, name = ask_llm_is_faq(row["text"] or "")
                decision_source, is_faq, llm_conf, llm_model = "llm", bool(v), float(c), name

            recs.append(LabelRecord(
                course_id=row["course_id"], message_id=f"{row['course_id']}:{row['ts_raw']}",
                ts=row["ts"].isoformat() if row["ts"] is not None else None,
                thread_ts=row["thread_ts"].isoformat() if row["thread_ts"] is not None else None,
                is_thread_head=bool(row["is_thread_head"]), text=row["text"],
                is_faq=bool(is_faq), score=float(p), decision_source=decision_source,
                threshold_low=float(self.low), threshold_high=float(self.high),
                classifier_name=self.clf.name, classifier_version=self.clf.version,
                llm_model=llm_model, llm_confidence=llm_conf,
                year=int(row["year"]), month=int(row["month"]), day=int(row["day"]),
            ).model_dump())

        if recs:
            pa_tbl = pa.Table.from_pylist(recs)
            self._write_labels(pa_tbl, course_id, int(df["year"].iloc[0]), int(df["month"].iloc[0]), int(df["day"].iloc[0]))
```

**`classifier/batch_run.py`**
```python
import fsspec
from .hybrid import HybridClassifier

def run_all_courses(bucket="dtc-slack-data-prod", courses=("ml-zoomcamp","de-zoomcamp")):
    clf = HybridClassifier(bucket=bucket)
    fs = fsspec.filesystem("s3")
    for course in courses:
        root = f"s3://{bucket}/bronze/slack/messages/course_id={course}"
        for y_path in fs.ls(root):
            y = int(y_path.split("year=")[1].split("/")[0])
            for m_path in fs.ls(y_path):
                m = int(m_path.split("month=")[1].split("/")[0])
                for d_path in fs.ls(m_path):
                    d = int(d_path.split("day=")[1].split("/")[0])
                    clf.process_partition(course, y, m, d)

if __name__ == "__main__":
    run_all_courses()
```

**`classifier/daily_run.py`**
```python
from datetime import date
from .hybrid import HybridClassifier

def run_today(course_id:str, bucket="dtc-slack-data-prod"):
    clf = HybridClassifier(bucket=bucket)
    today = date.today()
    clf.process_partition(course_id, today.year, today.month, today.day)

if __name__ == "__main__":
    run_today("ml-zoomcamp")
```

Run with uv:
```bash
uv run python classifier/batch_run.py   # historical
uv run python classifier/daily_run.py   # daily
```

---

## 6) Historical vs daily

- **Historical backfill**: bootstrap labels (LLM + human audit → SetFit fine-tune), then run `classifier/batch_run.py`; only uncertainty band uses LLM.  
- **Daily**: dlt ingests JSON to bronze; `classifier/daily_run.py` scores the new day; LLM only for the uncertainty band.  
- Keep a **30‑day confusion audit** and periodically **retrain** the small model with fresh labels.

---

## 7) Notes

- Classification is **out of dlt** → ingestion is stable, re‑label anytime.  
- Parquet compression: **ZSTD**, partitions: `course_id/year/month/day`.  
- If you need upserts/time‑travel, consider Iceberg/Delta/Hudi on S3; DuckDB/Athena can still query.  
- For uv-only workflows, prefer `uv add`, `uv sync`, and `uv run`; avoid mixing in `pip`.

---

## 8) Quick commands (copy/paste)

```bash
# 1) Infra
cd infra/terraform/s3 && terraform init
terraform apply -auto-approve -var="bucket_name=dtc-slack-data-prod" -var="aws_region=ap-south-1"

# 2) Deps (uv)
uv add dlt pyarrow s3fs fsspec orjson python-dateutil pyyaml
uv add setfit datasets sentence-transformers pydantic duckdb
uv sync

# 3) Ingest (dlt)
uv run python data-ingestion/pipeline/slack_pipeline.py

# 4) Label (hybrid)
uv run python classifier/batch_run.py
# or
uv run python classifier/daily_run.py
```
