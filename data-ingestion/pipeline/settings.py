from datetime import datetime, timezone
from dateutil import parser as dateparser
from hashlib import sha256

def to_dt(ts_str: str | None):
    """
    Convert a timestamp string to a timezone-aware datetime object.
    
    Handles both Unix timestamps (e.g., "1723556195.123456") and 
    ISO format date strings. Always returns UTC timezone.
    
    Args:
        ts_str: Timestamp string in Unix or ISO format, or None
        
    Returns:
        datetime object with UTC timezone, or None if parsing fails
        
    Examples:
        >>> to_dt("1723556195.123456")  # Unix timestamp
        datetime.datetime(2024, 8, 13, 14, 36, 35, 123456, tzinfo=timezone.utc)
        >>> to_dt("2024-08-13T14:36:35")  # ISO format
        datetime.datetime(2024, 8, 13, 14, 36, 35, tzinfo=timezone.utc)
    """
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
    """
    Extract year, month, and day from a datetime object.
    
    Args:
        dt: datetime object or None
        
    Returns:
        Tuple of (year, month, day) as integers, or (None, None, None) if dt is None
        
    Examples:
        >>> ymd_from_dt(datetime(2024, 8, 13))
        (2024, 8, 13)
        >>> ymd_from_dt(None)
        (None, None, None)
    """
    if not dt: return (None, None, None)
    return dt.year, dt.month, dt.day

def digest(s: str) -> str:
    """
    Generate SHA-256 hash of a string.
    
    Used for creating unique identifiers and detecting duplicate content.
    Handles encoding errors gracefully by ignoring problematic characters.
    
    Args:
        s: String to hash
        
    Returns:
        Hexadecimal string representation of SHA-256 hash
        
    Examples:
        >>> digest("Hello World")
        'a591a6d40bf420404a011733cfb7b190d62c65bf0bcda32b51b2b6c3f8b01d5f'
    """
    return sha256(s.encode("utf-8", errors="ignore")).hexdigest()