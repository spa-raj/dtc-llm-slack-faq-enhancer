"""
Slack API to S3 Raw Data Ingestion Pipeline

This module fetches messages from Slack public channels within a specified time window
and stores them as raw JSON files in S3 with date-based partitioning.

It also exposes a dlt-compatible resource wrapper (`slack_messages_dlt`)
so one can plug into a dlt pipeline later (for incremental state, observability, etc.)
without changing your output contract. Enable it at runtime with:

    USE_DLT_RESOURCE=1

Security features:
- OIDC authentication (no static credentials)
- Optional SSE-KMS encryption
- Atomic writes with temporary files
- Rate limiting with exponential backoff + jitter
- Environment variable based configuration
"""


from __future__ import annotations
import argparse, os, time, uuid, hashlib, random, re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import orjson, fsspec
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from settings import to_dt, ymd_from_dt
import yaml
import dlt

def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    """
    Get environment variable value with optional default.
    
    Args:
        name: Environment variable name
        default: Default value if environment variable is not set
        
    Returns:
        Environment variable value or default
    """
    v = os.environ.get(name)
    return v if v is not None else default

def _substitute_env_vars(text: str) -> str:
    """
    Replace ${VAR_NAME} placeholders with environment variable values.
    
    Args:
        text: Text containing ${VAR_NAME} placeholders
        
    Returns:
        Text with placeholders replaced by environment variable values
        
    Raises:
        ValueError: If a referenced environment variable is not set
        
    Example:
        >>> os.environ['BUCKET'] = 'my-bucket'
        >>> _substitute_env_vars('s3://${BUCKET}/data')
        's3://my-bucket/data'
    """
    def replacer(match):
        var_name = match.group(1)
        # Skip comment lines and documentation examples
        if var_name == "VAR_NAME":
            return match.group(0)  # Return the original placeholder
        value = os.environ.get(var_name)
        if value is None:
            raise ValueError(f"Environment variable {var_name} is not set")
        return value
    
    return re.sub(r'\$\{([^}]+)\}', replacer, text)

def _jitter_sleep(ms: Optional[int]):
    """
    Sleep for specified milliseconds to add jitter between API calls.
    
    Args:
        ms: Milliseconds to sleep, or None to skip
        
    Note:
        Used to prevent hitting rate limits by spacing out API calls
    """
    if not ms: 
        return
    time.sleep(ms / 1000.0)

def _backoff_sleep(base: float, factor: float, attempt: int, cap: float) -> float:
    """
    Implement exponential backoff with jitter for retry logic.
    
    Args:
        base: Base delay in seconds
        factor: Exponential growth factor
        attempt: Current attempt number (0-indexed)
        cap: Maximum delay in seconds
        
    Returns:
        Actual delay applied (including jitter)
        
    Note:
        Adds 0-250ms of random jitter to prevent thundering herd
    """
    delay = min(cap, base * (factor ** attempt))
    # add 0-250ms jitter
    delay += random.random() * 0.25
    time.sleep(delay)
    return delay

def _make_fs():
    """
    Create S3 filesystem client with optional KMS encryption.
    
    Uses environment variables:
        AWS_REGION: AWS region for S3 client
        S3_SSE: Server-side encryption mode ('aws:kms' or 'AES256')
        S3_SSE_KMS_KEY_ID: KMS key ARN/ID for SSE-KMS
        
    Returns:
        fsspec S3 filesystem instance configured with encryption settings
        
    Note:
        Falls back to SSE-S3 if KMS is not configured
    """
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

def _sleep_on_ratelimit(e: Exception, attempt: int, cap: float) -> bool:
    """
    Handle Slack API rate limiting with intelligent retry.
    
    Args:
        e: Exception to check for rate limiting
        attempt: Current retry attempt number
        cap: Maximum backoff delay in seconds
        
    Returns:
        True if rate limited and sleep was applied, False otherwise
        
    Note:
        Respects Slack's Retry-After header and adds exponential backoff
    """
    if isinstance(e, SlackApiError) and getattr(e, "response", None):
        if e.response.get("error") == "ratelimited":
            retry_after = int(e.response.headers.get("retry-after", 1))
            # add small jitter (0-300ms)
            time.sleep(retry_after + (random.random() * 0.3) + 0.5)
            # extra exponential backoff on repeated 429s for safety
            _backoff_sleep(base=1.0, factor=1.5, attempt=attempt, cap=cap)
            return True
    return False

def fetch_24h(client: WebClient, channel_id: str, oldest: str, latest: str, 
              jitter_ms: Optional[int], backoff_cap: float) -> List[dict]:
    """
    Fetch all messages and thread replies from a Slack channel within time window.
    
    Args:
        client: Slack WebClient instance
        channel_id: Slack channel ID to fetch from
        oldest: Unix timestamp string for oldest message
        latest: Unix timestamp string for latest message
        jitter_ms: Milliseconds to sleep between API calls
        backoff_cap: Maximum backoff delay in seconds for rate limiting
        
    Returns:
        List of message dictionaries including thread replies
        
    Note:
        - Handles pagination automatically
        - Fetches thread replies for each parent message
        - Implements rate limiting and retry logic
        - Returns raw Slack message objects
    """
    # Fetch conversation history
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

    # Fetch thread replies
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
                    # Skip the first message (it's the parent, already added)
                    replies = rr["messages"][1:] if len(rr["messages"]) > 1 else []
                    out.extend(replies)
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

@dlt.resource(name="slack_messages", selected=True)
def slack_messages_dlt(
    courses_cfg: List[dict],
    oldest: str,
    latest: str,
    jitter_ms: Optional[int],
    backoff_cap: float,
    slack_token: Optional[str] = None,
):
    """
    dlt resource wrapper that yields enriched Slack messages.

    This wraps the existing custom reader (`fetch_24h`) so we keep
    the pagination, replies fetching, and rate-limit handling intact,
    while exposing a dlt-compatible resource for future pipelines.

    Args:
        courses_cfg: List of course dicts with keys {"id", "channels": [...]}
        oldest: Slack 'oldest' timestamp string (seconds, with decimals)
        latest: Slack 'latest' timestamp string (seconds, with decimals)
        jitter_ms: Optional per-page jitter to reduce thundering herd
        backoff_cap: Max backoff seconds for repeated 429s
        slack_token: Optional Slack bot token; falls back to env if None

    Yields:
        dict: Raw Slack message object enriched with
              {course_id, channel_id, fetched_at} fields.
    """
    token = slack_token or os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        raise RuntimeError("SLACK_BOT_TOKEN is not set")

    client = WebClient(token=token)
    fetched_at = datetime.now(timezone.utc).isoformat()

    for course in courses_cfg:
        cid = course["id"]
        for channel_id in course.get("channels", []):
            msgs = fetch_24h(
                client,
                channel_id,
                oldest,
                latest,
                jitter_ms=jitter_ms,
                backoff_cap=backoff_cap,
            )
            for m in msgs:
                m_enriched = dict(m)
                m_enriched["course_id"] = cid
                m_enriched["channel_id"] = channel_id
                m_enriched["fetched_at"] = fetched_at
                yield m_enriched


def _final_key(course_id: str, y: int, m: int, d: int) -> str:
    """
    Generate S3 key path for final data file.
    
    Args:
        course_id: Course identifier
        y: Year (4 digits)
        m: Month (1-12)
        d: Day (1-31)
        
    Returns:
        S3 key path following partition structure
        
    Example:
        >>> _final_key('ml-zoomcamp', 2024, 8, 19)
        'raw/slack/ml-zoomcamp/year=2024/month=08/day=19/2024-08-19.json'
    """
    return f"raw/slack/{course_id}/year={y}/month={m:02d}/day={d:02d}/{y}-{m:02d}-{d:02d}.json"

def _tmp_key(final_key: str) -> str:
    """
    Generate temporary S3 key for atomic writes.
    
    Args:
        final_key: Final destination key path
        
    Returns:
        Temporary key path with UUID for uniqueness
        
    Note:
        Used for atomic writes - write to temp, then copy to final
    """
    return f"raw/slack/_tmp/{uuid.uuid4().hex}/{Path(final_key).name}"

def write_grouped_s3(fs, bucket: str, batches: Dict[Tuple[str, int, int, int], List[dict]]):
    """
    Write message batches to S3 with optional atomic writes and checksums.
    
    Args:
        fs: S3 filesystem instance
        bucket: S3 bucket name
        batches: Dictionary mapping (course_id, year, month, day) to message lists
        
    Returns:
        List of S3 URIs that were written
        
    Environment variables used:
        S3_WRITE_ATOMIC: If '1', use atomic writes (temp then copy)
        S3_WRITE_SHA256: If '1', write SHA-256 checksum sidecar files
        
    Note:
        - Groups messages by course and date
        - Writes one JSON file per course-day combination
        - Supports atomic writes to prevent partial file corruption
        - Can generate SHA-256 checksums for integrity verification
    """
    atomic = _env("S3_WRITE_ATOMIC", "1") == "1"
    write_sha = _env("S3_WRITE_SHA256", "0") == "1"
    
    written_files = []

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
        
        written_files.append(final_uri)
        print(f"Written: {final_uri} ({len(msgs)} messages)")
    
    return written_files

def load_courses_config(courses_yaml: str) -> List[dict]:
    """
    Load courses configuration from YAML with environment variable substitution.
    
    Args:
        courses_yaml: Path to courses YAML configuration file
        
    Returns:
        List of course dictionaries with channel IDs and settings
        
    Raises:
        ValueError: If referenced environment variables are not set
        FileNotFoundError: If YAML file doesn't exist
        
    Note:
        Substitutes ${VAR_NAME} placeholders in YAML with environment values
    """
    yaml_content = Path(courses_yaml).read_text(encoding="utf-8")
    # Substitute environment variables in the YAML content
    yaml_content = _substitute_env_vars(yaml_content)
    cfg = yaml.safe_load(yaml_content)
    return cfg.get("courses", [])

def main():
    """
    Main entry point for Slack to S3 ingestion pipeline.
    
    Workflow:
        1. Load configuration from environment variables and arguments
        2. Initialize Slack client and S3 filesystem
        3. Calculate time window for message fetching
        4. Load course configuration with channel mappings
        5. Fetch messages from each channel
        6. Enrich messages with metadata
        7. Group by course and date
        8. Write to S3 with partitioning
        
    Environment variables required:
        SLACK_BOT_TOKEN: Slack bot token with channels:read and channels:history
        BUCKET_DATA: Target S3 bucket name
        AWS_REGION: AWS region for S3
        SLACK_S3_WRITER_ROLE_NAME: IAM role name for OIDC (GitHub Actions)
        SLACK_CHANNEL_*: Channel IDs for each course
        
    Optional environment variables:
        WINDOW_HOURS: Hours to look back (default: 24)
        S3_SSE: Encryption mode (aws:kms or AES256)
        S3_SSE_KMS_KEY_ID: KMS key for encryption
        S3_WRITE_ATOMIC: Enable atomic writes (default: 1)
        S3_WRITE_SHA256: Write SHA-256 checksums (default: 0)
        RATE_JITTER_MS: Jitter between API calls in ms
        RATE_MAX_BACKOFF_S: Maximum backoff for rate limiting
    """
    ap = argparse.ArgumentParser(description="Fetch Slack messages from public channels and store in S3")
    ap.add_argument("--bucket", help="S3 bucket (overrides BUCKET_DATA)")
    ap.add_argument("--courses-yaml", help="Path to courses YAML (overrides COURSES_YAML)")
    ap.add_argument("--window-hours", type=int, help="Hours window (overrides WINDOW_HOURS)")
    args = ap.parse_args()

    # env-first configuration
    bucket = args.bucket or _env("BUCKET_DATA")
    courses_yaml = args.courses_yaml or _env("COURSES_YAML", "data-ingestion/pipeline/courses.yml")
    window_hours = args.window_hours or int(_env("WINDOW_HOURS", "24") or "24")
    jitter_ms = int(_env("RATE_JITTER_MS", "0") or "0")
    backoff_cap = float(_env("RATE_MAX_BACKOFF_S", "30") or "30")

    token = _env("SLACK_BOT_TOKEN")
    if not token:
        raise RuntimeError("SLACK_BOT_TOKEN is not set")

    if not bucket:
        raise RuntimeError("BUCKET_DATA (or --bucket) is required")
    if not courses_yaml or not Path(courses_yaml).exists():
        raise RuntimeError(f"COURSES_YAML (or --courses-yaml) is missing or not found: {courses_yaml}")

    print(f"Configuration:")
    print(f"  Bucket: {bucket}")
    print(f"  Window: {window_hours} hours")
    print(f"  Courses YAML: {courses_yaml}")
    print(f"  Rate jitter: {jitter_ms}ms")
    print(f"  Max backoff: {backoff_cap}s")
    print()

    client = WebClient(token=token)
    fs = _make_fs()

    now = datetime.now(timezone.utc)
    oldest_dt = now - timedelta(hours=window_hours)
    oldest = str(oldest_dt.timestamp())
    latest = str(now.timestamp())

    print(f"Time window: {oldest_dt.isoformat()} to {now.isoformat()}")
    print()

    courses = load_courses_config(courses_yaml)
    print(f"Loaded {len(courses)} courses")

    grouped: Dict[Tuple[str, int, int, int], List[dict]] = {}
    fetched_at = now.isoformat()

    use_dlt = os.environ.get("USE_DLT_RESOURCE", "0") == "1"

    total_messages = 0
    total_channels = 0

    if use_dlt:
        print("Using dlt resource wrapper (slack_messages_dlt) to fetch messages...")
        total_channels = sum(len(c.get("channels", [])) for c in courses)

        for m in slack_messages_dlt(
            courses_cfg=courses,
            oldest=oldest,
            latest=latest,
            jitter_ms=jitter_ms,
            backoff_cap=backoff_cap,
            slack_token=token,
        ):
            total_messages += 1
            dt = to_dt(m.get("ts"))
            y, mth, d = ymd_from_dt(dt)
            if not all([y, mth, d]):
                continue
            grouped.setdefault((m["course_id"], y, mth, d), []).append(m)

        print(f"Fetched ~{total_messages} messages across {total_channels} channels via dlt resource")

    else:
        print("Using custom per-channel fetcher (existing path)...")

        for course in courses:
            cid = course["id"]
            for channel_id in course.get("channels", []):
                total_channels += 1
                try:
                    msgs = fetch_24h(
                        client, channel_id, oldest, latest,
                        jitter_ms=jitter_ms, backoff_cap=backoff_cap
                    )
                    total_messages += len(msgs)
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
                except Exception as e:
                    print(f"    Error fetching channel {channel_id}: {e}")
                    continue


    print(f"\nTotal: {total_messages} messages from {total_channels} channels")
    print(f"Writing to S3...")
    
    written_files = write_grouped_s3(fs, bucket, grouped)
    
    print(f"\nSuccessfully written {len(written_files)} files to S3")

if __name__ == "__main__":
    main()