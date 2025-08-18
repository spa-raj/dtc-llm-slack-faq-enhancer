"""
Daily processing script for incremental FAQ classification.

Processes new messages from today's data in the bronze layer
and appends results to the gold layer.
"""
from datetime import date
from .hybrid import HybridClassifier

def run_today(course_id: str = None, bucket="dtc-slack-data-prod"):
    """
    Process today's messages for FAQ classification.
    
    Args:
        course_id: Specific course to process (None = all courses)
        bucket: S3 bucket name
    """
    clf = HybridClassifier(bucket=bucket)
    today = date.today()
    
    courses = [course_id] if course_id else [
        "course-data-engineering",
        "course-llm-zoomcamp",
        "course-mlops-zoomcamp",
        "course-ml-zoomcamp",
        "course-stocks-analytics-zoomcamp"
    ]
    
    for course in courses:
        print(f"Processing {course} for {today}")
        try:
            clf.process_partition(course, today.year, today.month, today.day)
            print(f"  Successfully processed {course}")
        except Exception as e:
            print(f"  Error processing {course}: {e}")

def run_date_range(start_date: date, end_date: date, course_id: str = None, 
                  bucket="dtc-slack-data-prod"):
    """
    Process messages for a specific date range.
    
    Useful for backfilling specific periods or reprocessing after
    model improvements.
    
    Args:
        start_date: Start date (inclusive)
        end_date: End date (inclusive)
        course_id: Specific course to process (None = all courses)
        bucket: S3 bucket name
    """
    clf = HybridClassifier(bucket=bucket)
    
    courses = [course_id] if course_id else [
        "course-data-engineering",
        "course-llm-zoomcamp",
        "course-mlops-zoomcamp",
        "course-ml-zoomcamp",
        "course-stocks-analytics-zoomcamp"
    ]
    
    current = start_date
    while current <= end_date:
        for course in courses:
            print(f"Processing {course} for {current}")
            try:
                clf.process_partition(course, current.year, current.month, current.day)
            except Exception as e:
                print(f"  Error: {e}")
        
        # Move to next day
        current = date(current.year, current.month, current.day + 1)

if __name__ == "__main__":
    # Run for today by default
    run_today()