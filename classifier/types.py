"""
Type definitions for the classifier service.

Defines Pydantic models for structured data validation and serialization.
"""
from pydantic import BaseModel
from typing import Optional

class LabelRecord(BaseModel):
    """
    Represents a labeled FAQ message record for the gold layer.
    
    Attributes:
        course_id: Identifier for the course/channel
        message_id: Unique identifier for the message (course_id:timestamp)
        ts: ISO format timestamp of the message
        thread_ts: ISO format timestamp of the thread parent
        is_thread_head: Whether this message starts a thread
        text: Original message text
        is_faq: Classification result - whether message is an FAQ
        score: Confidence score from the model (0.0 to 1.0)
        decision_source: How the decision was made ("model" or "llm")
        threshold_low: Lower threshold for uncertainty band
        threshold_high: Upper threshold for uncertainty band
        classifier_name: Name of the primary classifier used
        classifier_version: Version of the primary classifier
        llm_model: Name of LLM model used (if decision_source="llm")
        llm_confidence: Confidence score from LLM (if used)
        canonical_id: ID of canonical FAQ this maps to (future feature)
        canonical_text: Text of canonical FAQ (future feature)
        embedding_model: Model used for embeddings (future feature)
        embedding_version: Version of embedding model (future feature)
        year: Year from message timestamp for partitioning
        month: Month from message timestamp for partitioning
        day: Day from message timestamp for partitioning
    """
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