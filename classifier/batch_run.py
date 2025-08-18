"""
Batch processing script for historical FAQ classification.

Processes all historical messages in the bronze layer and
creates gold layer with FAQ labels.
"""
import fsspec
from .hybrid import HybridClassifier

def run_all_courses(bucket="dtc-slack-data-prod", 
                   courses=("course-data-engineering", "course-llm-zoomcamp", 
                           "course-mlops-zoomcamp", "course-ml-zoomcamp", 
                           "course-stocks-analytics-zoomcamp")):
    """
    Process all courses in batch mode.
    
    Iterates through all partitions in the bronze layer for each course
    and applies the hybrid classification pipeline.
    
    Args:
        bucket: S3 bucket name
        courses: Tuple of course IDs to process
    """
    clf = HybridClassifier(bucket=bucket)
    fs = fsspec.filesystem("s3")
    
    for course in courses:
        print(f"Processing course: {course}")
        root = f"s3://{bucket}/bronze/slack/messages/course_id={course}"
        
        try:
            # Iterate through year partitions
            for y_path in fs.ls(root):
                y = int(y_path.split("year=")[1].split("/")[0])
                
                # Iterate through month partitions
                for m_path in fs.ls(y_path):
                    m = int(m_path.split("month=")[1].split("/")[0])
                    
                    # Iterate through day partitions
                    for d_path in fs.ls(m_path):
                        d = int(d_path.split("day=")[1].split("/")[0])
                        
                        print(f"  Processing partition: {y:04d}-{m:02d}-{d:02d}")
                        clf.process_partition(course, y, m, d)
                        
        except Exception as e:
            print(f"Error processing course {course}: {e}")
            continue

if __name__ == "__main__":
    run_all_courses()