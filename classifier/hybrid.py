"""
Hybrid classifier module combining SetFit and LLM fallback.

Processes messages from bronze layer and produces gold layer
with FAQ labels and confidence scores.
"""
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import fsspec
from datetime import timezone, datetime
from .prefilter import is_question_like
from .setfit_model import SetFitWrapper
from .llm_fallback import ask_llm_is_faq
from .types import LabelRecord

class HybridClassifier:
    """
    Hybrid classification system for FAQ detection.
    
    Combines:
    - Pre-filtering to identify question-like messages
    - SetFit model for primary classification
    - LLM fallback for uncertain cases
    
    Attributes:
        bucket: S3 bucket name
        bronze: Path to bronze layer data
        gold: Path to gold layer output
        low: Lower threshold for uncertainty band
        high: Upper threshold for uncertainty band
        clf: SetFit classifier instance
    """
    
    def __init__(self, bucket="dtc-slack-data-prod", bronze_prefix="bronze/slack/messages",
                 gold_prefix="gold/faq_labels", low=0.45, high=0.65):
        """
        Initialize the hybrid classifier.
        
        Args:
            bucket: S3 bucket name for data lake
            bronze_prefix: Prefix path for bronze layer messages
            gold_prefix: Prefix path for gold layer labels
            low: Lower threshold for uncertainty band (triggers LLM)
            high: Upper threshold for uncertainty band (triggers LLM)
        """
        self.bucket = bucket
        self.bronze = f"s3://{bucket}/{bronze_prefix}"
        self.gold   = f"s3://{bucket}/{gold_prefix}"
        self.low, self.high = low, high
        self.clf = SetFitWrapper()

    def _read_messages(self, course_id: str, y: int, m: int, d: int):
        """
        Read messages from bronze layer for a specific partition.
        
        Args:
            course_id: Course identifier
            y: Year
            m: Month
            d: Day
            
        Returns:
            PyArrow table with message data
        """
        path = f"{self.bronze}/course_id={course_id}/year={y}/month={m:02d}/day={d:02d}"
        dataset = ds.dataset(path, format="parquet", filesystem=fsspec.filesystem("s3"))
        return dataset.to_table(columns=[
            "course_id", "ts", "ts_raw", "thread_ts", "thread_ts_raw", 
            "is_thread_head", "text", "year", "month", "day"
        ])

    def _write_labels(self, table: pa.Table, course_id: str, y: int, m: int, d: int):
        """
        Write labeled data to gold layer.
        
        Args:
            table: PyArrow table with label records
            course_id: Course identifier
            y: Year
            m: Month
            d: Day
        """
        out = f"{self.gold}/course_id={course_id}/year={y}/month={m:02d}/day={d:02d}"
        fs = fsspec.filesystem("s3")
        pq.write_to_dataset(table, root_path=out, filesystem=fs, compression="zstd")

    def process_partition(self, course_id: str, y: int, m: int, d: int):
        """
        Process a single partition of messages.
        
        Applies the full classification pipeline:
        1. Read messages from bronze
        2. Filter for thread heads and question-like text
        3. Classify with SetFit
        4. Use LLM for uncertain cases
        5. Write results to gold
        
        Args:
            course_id: Course identifier
            y: Year
            m: Month
            d: Day
        """
        # Read messages from bronze
        tab = self._read_messages(course_id, y, m, d)
        df = tab.to_pandas()

        # Filter for thread heads that look like questions
        cand = df[(df["is_thread_head"] == True) & (df["text"].astype(str).map(is_question_like))].copy()
        if cand.empty:
            return

        # Get predictions from SetFit model
        probs = self.clf.predict_proba(cand["text"].tolist())
        
        # Process each candidate message
        recs = []
        for (_, row), p in zip(cand.iterrows(), probs):
            decision_source = "model"
            is_faq = p >= 0.5
            llm_model = None
            llm_conf = None

            # Check if score falls in uncertainty band
            if self.low <= p <= self.high:
                # Use LLM for uncertain cases
                v, c, name = ask_llm_is_faq(row["text"] or "")
                decision_source = "llm"
                is_faq = bool(v)
                llm_conf = float(c)
                llm_model = name

            # Create label record
            recs.append(LabelRecord(
                course_id=row["course_id"],
                message_id=f"{row['course_id']}:{row['ts_raw']}",
                ts=row["ts"].isoformat() if row["ts"] is not None else None,
                thread_ts=row["thread_ts"].isoformat() if row["thread_ts"] is not None else None,
                is_thread_head=bool(row["is_thread_head"]),
                text=row["text"],
                is_faq=bool(is_faq),
                score=float(p),
                decision_source=decision_source,
                threshold_low=float(self.low),
                threshold_high=float(self.high),
                classifier_name=self.clf.name,
                classifier_version=self.clf.version,
                llm_model=llm_model,
                llm_confidence=llm_conf,
                year=int(row["year"]),
                month=int(row["month"]),
                day=int(row["day"]),
            ).model_dump())

        # Write results to gold layer if any records exist
        if recs:
            pa_tbl = pa.Table.from_pylist(recs)
            self._write_labels(
                pa_tbl, 
                course_id, 
                int(df["year"].iloc[0]), 
                int(df["month"].iloc[0]), 
                int(df["day"].iloc[0])
            )