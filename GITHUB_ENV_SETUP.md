# GitHub Environment Setup for Slack to S3 Pipeline

## Required GitHub Environment Configuration

Create a GitHub Environment named `dev` with the following secrets and variables:

### Secrets (Settings → Secrets and variables → Actions → Environment secrets)

| Secret Name | Description | Example |
|------------|-------------|---------|
| `SLACK_BOT_TOKEN` | Slack bot token with channels:read and channels:history scopes | `xoxb-...` |

### Variables (Settings → Secrets and variables → Actions → Environment variables)

| Variable Name | Required | Description | Example |
|--------------|----------|-------------|---------|
| `BUCKET_DATA` | Yes | Target S3 bucket for raw data | `dtc-slack-data-dev` |
| `AWS_REGION` | Yes | AWS region for S3 | `ap-south-1` |
| `AWS_ACCOUNT_ID` | Yes | AWS Account ID | `123456789012` |
| `SLACK_S3_WRITER_ROLE_NAME` | Yes | IAM role name for Slack S3 writer (OIDC) | `gha-slack-s3-writer-dev` |
| `COURSES_YAML` | No | Path to courses configuration (auto-detected if not set) | `data-ingestion/pipeline/courses.yml` |
| `SLACK_CHANNEL_DATA_ENGINEERING` | Yes | Slack channel ID for Data Engineering course | `C01234567890` |
| `SLACK_CHANNEL_LLM_ZOOMCAMP` | Yes | Slack channel ID for LLM Zoomcamp | `C01234567891` |
| `SLACK_CHANNEL_MLOPS_ZOOMCAMP` | Yes | Slack channel ID for MLOps Zoomcamp | `C01234567892` |
| `SLACK_CHANNEL_ML_ZOOMCAMP` | Yes | Slack channel ID for ML Zoomcamp | `C01234567893` |
| `SLACK_CHANNEL_STOCKS_ANALYTICS` | Yes | Slack channel ID for Stocks Analytics | `C01234567894` |
| `WINDOW_HOURS` | No | Hours to look back (default: 24) | `24` |
| `S3_SSE` | No | S3 encryption mode | `aws:kms` or `AES256` |
| `S3_SSE_KMS_KEY_ID` | No | KMS key ARN for SSE-KMS | `arn:aws:kms:region:account:key/id` |
| `S3_WRITE_ATOMIC` | No | Enable atomic writes (default: 1) | `1` |
| `S3_WRITE_SHA256` | No | Write SHA-256 checksums (default: 0) | `0` |
| `RATE_JITTER_MS` | No | Jitter between API calls in ms | `150` |
| `RATE_MAX_BACKOFF_S` | No | Max backoff for rate limiting | `30` |

## How to Get Slack Channel IDs

1. Open Slack in your browser
2. Navigate to the channel
3. Click on the channel name at the top
4. Look for the Channel ID in the URL or channel details
5. It will be in format like `C01234567890`

## AWS IAM Role Requirements

The IAM role specified as `SLACK_S3_WRITER_ROLE_NAME` should have:
- Trust relationship with GitHub Actions OIDC provider
- Permissions to write to the S3 bucket under `raw/slack/*` prefix
- If using KMS, permissions to use the specified KMS key

## Running the Pipeline

### Manual Trigger
1. Go to Actions tab in GitHub
2. Select "02 - Slack Raw Data Upload to S3" workflow
3. Click "Run workflow"

### Scheduled Execution
The pipeline is configured to run daily at 11:00 AM IST (currently commented out for testing)

## Local Development

For local testing, create a `.env` file with the same variables:

```bash
export SLACK_BOT_TOKEN=xoxb-...
export BUCKET_DATA=dtc-slack-data-dev
export AWS_REGION=ap-south-1
export SLACK_CHANNEL_DATA_ENGINEERING=C01234567890
# ... other variables

# Run the pipeline
uv sync --group ingest
uv run python data-ingestion/pipeline/slack_api_to_s3_raw.py
```

## Monitoring

Check the GitHub Actions tab for workflow runs and logs. Each run will show:
- Number of messages fetched
- Channels processed
- Files written to S3
- Any errors encountered