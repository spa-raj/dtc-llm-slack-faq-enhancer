# S3 Partition Structure Documentation

## Overview
This document defines the canonical partition structure used across all data ingestion pipelines for the Slack FAQ enhancer project.

## Partition Key Structure

### Raw Layer (JSON)
```
s3://bucket/raw/slack/{course_id}/year={YYYY}/month={MM}/day={DD}/{YYYY-MM-DD}.json
```

**Example:**
```
s3://dtc-slack-data-prod/raw/slack/course-data-engineering/year=2023/month=06/day=15/2023-06-15.json
```

### Bronze Layer (Parquet)
```
s3://bucket/bronze/slack/messages/course_id={course_id}/year={YYYY}/month={MM}/day={DD}/part-*.parquet
```

### Gold Layer (Parquet)
```
s3://bucket/gold/faq_labels/course_id={course_id}/year={YYYY}/month={MM}/day={DD}/part-*.parquet
```

## Key Components

1. **course_id**: The Slack channel/course identifier (e.g., `course-data-engineering`)
2. **year**: 4-digit year (e.g., `2023`)
3. **month**: 2-digit zero-padded month (e.g., `06` for June)
4. **day**: 2-digit zero-padded day (e.g., `15`)
5. **filename**: Date-based filename in format `YYYY-MM-DD.json`

## Available Courses

The following course IDs are configured in the system:
- `course-data-engineering`
- `course-llm-zoomcamp`
- `course-mlops-zoomcamp`
- `course-ml-zoomcamp`
- `course-stocks-analytics-zoomcamp`

## Usage Across Pipelines

### 1. Historical Data Upload (`upload_historical_dumps.py`)
- **Purpose**: One-time upload of historical Slack dumps from local machine
- **Function**: `generate_s3_key()` creates the canonical S3 path
- **Input**: Local JSON files in format `YYYY-MM-DD.json`
- **Output**: S3 raw layer with partition structure

### 2. Daily Slack API Ingestion (future `fetch_slack_daily.py`)
- **Purpose**: Fetch new messages from Slack API daily
- **Function**: Will use same `generate_s3_key()` pattern
- **Input**: Slack API conversations.history endpoint
- **Output**: S3 raw layer with same partition structure

### 3. DLT Bronze Processing (`slack_pipeline.py`)
- **Purpose**: Process raw JSON to normalized Parquet format
- **Function**: `_path_ymd()` extracts partition keys from S3 paths
- **Input**: Raw JSON files from S3
- **Output**: Bronze Parquet files with extracted partition columns

## Partition Benefits

1. **Query Optimization**: Allows efficient filtering by date range
2. **Cost Reduction**: Reduces S3 scan costs with partition pruning
3. **Parallel Processing**: Enables parallel processing by date/course
4. **Data Lifecycle**: Simplifies data retention and archival policies
5. **Incremental Updates**: Easy to identify and process new data

## Implementation Consistency

All scripts that interact with S3 data must:
1. Use the same partition key naming (`year=`, `month=`, `day=`)
2. Use zero-padded values (e.g., `01` not `1`)
3. Keep filename format as `YYYY-MM-DD.json` for raw data
4. Extract date from filename if partition keys are missing

## Example Queries

### Athena/Presto Query with Partitions
```sql
SELECT * FROM raw_slack_messages
WHERE course_id = 'course-data-engineering'
  AND year = 2023
  AND month = 6
  AND day BETWEEN 10 AND 20;
```

### S3 Select with Prefix
```bash
aws s3 ls s3://dtc-slack-data-prod/raw/slack/course-data-engineering/year=2023/month=06/
```

## Migration Notes

For any future changes to partition structure:
1. Update all ingestion scripts simultaneously
2. Consider backward compatibility for existing data
3. Update this documentation
4. Test with small dataset first