from __future__ import annotations
from typing import Iterator, Dict, Any
from pathlib import Path
import dlt, fsspec, orjson
from dlt.common.time import ensure_pendulum_datetime
from .settings import to_dt, ymd_from_dt, digest

def _is_s3(path: str) -> bool:
    """Check if a path is an S3 URL."""
    return path.startswith("s3://")

def _iter_json_files(prefix: str):
    """
    Iterate over JSON files in a given path prefix.
    
    Args:
        prefix: Path prefix (local filesystem or S3 URL)
        
    Yields:
        Full paths to JSON files found
    """
    if _is_s3(prefix):
        fs = fsspec.filesystem("s3")
        for p in fs.find(prefix):
            if p.endswith(".json"):
                yield f"s3://{p}"
    else:
        for p in Path(prefix).rglob("*.json"):
            yield str(p)

def _path_ymd(path: str):
    """
    Extract year, month, day from a file path.
    
    Looks for Hive-style partitions (year=YYYY/month=MM/day=DD) first,
    then falls back to parsing the filename (YYYY-MM-DD.json format).
    
    Args:
        path: File path to parse
        
    Returns:
        Tuple of (year, month, day) or (None, None, None) if not found
    """
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
    """
    Open and parse a JSON file from local filesystem or S3.
    
    Args:
        path: Path to JSON file (local or S3 URL)
        
    Returns:
        Parsed JSON data
    """
    if _is_s3(path):
        fs = fsspec.filesystem("s3")
        with fs.open(path, "rb") as f: return orjson.loads(f.read())
    return orjson.loads(Path(path).read_bytes())

@dlt.resource(name="messages", write_disposition="append")
def messages_from_raw(raw_prefix: str, course_id: str) -> Iterator[Dict[str, Any]]:
    """
    Extract and normalize Slack messages from raw JSON files.
    
    Processes raw Slack export JSON files and yields normalized message records
    for the bronze layer. No classification or enrichment is performed here.
    
    Args:
        raw_prefix: Path prefix containing raw Slack JSON files
        course_id: Identifier for the course/channel
        
    Yields:
        Dict containing normalized message fields for bronze layer
    """
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
    """
    Run the dlt pipeline for a single course.
    
    Args:
        raw_prefix: Path prefix containing raw Slack JSON files for this course
        course_id: Identifier for the course/channel
    """
    pipe = dlt.pipeline(pipeline_name="slack_ingest_v2", destination="filesystem", dataset_name="slack")
    rows = messages_from_raw(raw_prefix=raw_prefix, course_id=course_id)
    info = pipe.run({"messages": rows}, loader_file_format="parquet", write_disposition="append")
    print(info)

def run_all():
    """
    Run the pipeline for all courses defined in courses.yml.
    
    Reads course configuration from courses.yml and processes each course sequentially.
    """
    import yaml
    from pathlib import Path
    cfg = yaml.safe_load((Path(__file__).parent / "courses.yml").read_text())
    for c in cfg["courses"]:
        run_course(raw_prefix=c["raw_prefix"], course_id=c["id"])

if __name__ == "__main__":
    run_all()