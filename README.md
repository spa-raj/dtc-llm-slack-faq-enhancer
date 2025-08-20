# dtc-llm-slack-faq-enhancer

A comprehensive pipeline for ingesting Slack channel data and enhancing FAQ capabilities using Large Language Models (LLM). This project automates the collection, processing, and storage of Slack messages from multiple educational channels.

## Table of Contents

- [Workflow Diagram](#workflow-diagram)
- [GitHub Workflows](#github-workflows)
  - [1. Infrastructure Deployment](#1-infrastructure-deployment-01-terraform-deployyml)
  - [2. Bot Channel Join](#2-bot-channel-join-02-bot-join-slack-channelsyml)
  - [3. Slack Data Ingestion](#3-slack-data-ingestion-03-slack-raw-upload-s3yml)
- [Data Output Structure](#data-output-structure)
- [Prerequisites for Reproduction](#prerequisites-for-reproduction)
- [Security Features](#security-features)

## Workflow Diagram

![workflow diagram](https://github.com/user-attachments/assets/de990e19-6416-4fc1-8b75-6c94c20b4f88)

## GitHub Workflows

This project includes three automated GitHub workflows that handle infrastructure deployment, bot setup, and data ingestion:

### 1. Infrastructure Deployment (`01-terraform-deploy.yml`)

**Purpose**: Deploys S3 infrastructure using Terraform for storing raw Slack data.

**Trigger**: Manual workflow dispatch with action selection (plan/apply/destroy)

**Key Features**:
- Uses OIDC authentication (no static credentials)
- Terraform state management with remote S3 backend
- Supports plan, apply, and destroy operations
- Environment-based configuration

**Required Environment Variables**:
```bash
# Repository Variables (Settings > Secrets and Variables > Actions > Variables)
BUCKET_DATA=your-data-bucket-name          # S3 bucket for storing data
BUCKET_STATE=your-terraform-state-bucket   # S3 bucket for Terraform state
STATE_PREFIX=terraform-state-prefix        # Prefix for state files
AWS_REGION=us-east-1                       # AWS region
AWS_ACCOUNT_ID=123456789012               # AWS account ID
TERRAFORM_ROLE_NAME=terraform-apply-dev # AWS IAM role to deploy S3 via terraform
```

**Required Secrets**:
- AWS OIDC role: `arn:aws:iam::${AWS_ACCOUNT_ID}:role/{TERRAFORM_ROLE_NAME}`

**To reproduce**:
1. Set up AWS OIDC for GitHub Actions
2. Configure the repository variables above
3. Go to Actions > "01 - Deploy S3 Infrastructure with Terraform"
4. Click "Run workflow" and select desired action (plan/apply/destroy)

**Code Components**:
- **Terraform Configuration**: `infra/terraform/s3/` - S3 bucket and policy definitions
- **Backend Config**: Remote state stored in `${BUCKET_STATE}/${STATE_PREFIX}/terraform.tfstate`
- **Variables**: Bucket name and region passed as Terraform variables

### 2. Bot Channel Join (`02-bot-join-slack-channels.yml`)

**Purpose**: Automatically joins the Slack bot to configured channels for data collection.

**Trigger**: Manual workflow dispatch (can be configured for automatic on push)

**Key Features**:
- Joins bot to multiple Slack channels
- Error handling for common issues (already joined, archived channels, etc.)
- Environment variable-based channel configuration
- Detailed logging and status reporting

**Required Environment Variables**:
```bash
# Repository Variables
SLACK_CHANNEL_DATA_ENGINEERING=C1234567890    # Data Engineering channel ID
SLACK_CHANNEL_LLM_ZOOMCAMP=C2345678901        # LLM Zoomcamp channel ID
SLACK_CHANNEL_MLOPS_ZOOMCAMP=C3456789012      # MLOps Zoomcamp channel ID
SLACK_CHANNEL_ML_ZOOMCAMP=C4567890123         # ML Zoomcamp channel ID
SLACK_CHANNEL_STOCKS_ANALYTICS=C5678901234    # Stocks Analytics channel ID
```

**Required Secrets**:
```bash
# Repository Secrets
SLACK_BOT_TOKEN=xoxb-your-bot-token-here    # Slack bot token with channels:read permission
```

**To reproduce**:
1. Create a Slack app and bot token with `channels:read` and `channels:join` permissions
2. Add the bot token as a repository secret
3. Configure channel IDs as repository variables
4. Go to Actions > "02 - Bot Join Slack Channels"
5. Click "Run workflow"

**Code Components**:
- **Script**: `data-ingestion/scripts/slack_bot_join_channels.py`
  - Authenticates with Slack API using bot token
  - Iterates through configured channel IDs
  - Handles rate limiting and error cases
  - Provides detailed status reporting

### 3. Slack Data Ingestion (`03-slack-raw-upload-s3.yml`)

**Purpose**: Fetches messages from Slack channels and stores them as raw JSON in S3 with date-based partitioning.

**Trigger**: 
- Daily at 6:00 AM UTC (11:30 AM IST) via cron schedule
- Manual workflow dispatch

**Key Features**:
- Fetches messages and thread replies from multiple channels
- Implements rate limiting and retry logic
- S3 storage with date-based partitioning
- Optional KMS encryption and atomic writes
- Configurable time windows for data collection

**Required Environment Variables**:
```bash
# AWS Configuration
BUCKET_DATA=your-data-bucket-name
AWS_REGION=us-east-1
AWS_ACCOUNT_ID=123456789012
SLACK_S3_WRITER_ROLE_NAME=gha-slack-s3-writer-dev

# Pipeline Configuration
WINDOW_HOURS=24                    # Hours to look back for messages
S3_SSE=aws:kms                     # Encryption type (optional)
S3_SSE_KMS_KEY_ID=your-kms-key     # KMS key for encryption (optional)
S3_WRITE_ATOMIC=1                  # Enable atomic writes
S3_WRITE_SHA256=0                  # Generate SHA256 checksums
RATE_JITTER_MS=500                 # Jitter between API calls
RATE_MAX_BACKOFF_S=30              # Maximum backoff for rate limiting

# Channel IDs (same as workflow 2)
SLACK_CHANNEL_DATA_ENGINEERING=C1234567890
SLACK_CHANNEL_LLM_ZOOMCAMP=C2345678901
SLACK_CHANNEL_MLOPS_ZOOMCAMP=C3456789012
SLACK_CHANNEL_ML_ZOOMCAMP=C4567890123
SLACK_CHANNEL_STOCKS_ANALYTICS=C5678901234
```

**Required Secrets**:
```bash
SLACK_BOT_TOKEN=xoxb-your-bot-token-here    # Slack bot token with channels:history permission
```

**To reproduce**:
1. Complete workflows 1 and 2 first (infrastructure + bot setup)
2. Ensure bot has `channels:history` permission
3. Configure all environment variables above
4. Set up AWS OIDC role with S3 write permissions
5. Go to Actions > "03 - Slack Raw Data Upload to S3"
6. Click "Run workflow" or wait for scheduled execution

**Code Components**:
- **Main Pipeline**: `data-ingestion/pipeline/slack_api_to_s3_raw.py`
  - Multi-channel message fetching with pagination
  - Thread reply collection
  - Rate limiting with exponential backoff
  - S3 integration with optional encryption
  - Date-based partitioning: `raw/slack/{course}/year={yyyy}/month={mm}/day={dd}/`

- **Configuration**: `data-ingestion/pipeline/courses.yml`
  - Maps course IDs to Slack channel IDs
  - Uses environment variable substitution
  - Defines S3 prefixes for each course

- **Dependencies**: Uses `uv` for Python dependency management
  - Core libraries: `slack-sdk`, `fsspec`, `orjson`, `dlt`
  - AWS authentication via OIDC

## Data Output Structure

Messages are stored in S3 with the following structure:
```
s3://your-bucket/raw/slack/{course-id}/year={yyyy}/month={mm}/day={dd}/{yyyy-mm-dd}.json
```

Each JSON file contains an array of enriched message objects with:
- Original Slack message fields (`ts`, `text`, `user`, etc.)
- Additional fields: `course_id`, `channel_id`, `fetched_at`
- Thread replies included alongside parent messages

## Prerequisites for Reproduction

1. **AWS Setup**:
   - AWS account with S3 and IAM permissions
   - OIDC provider configured for GitHub Actions
   - IAM roles for Terraform and S3 operations

2. **Slack Setup**:
   - Slack workspace with channels to monitor
   - Slack app with bot token
   - Required permissions: `channels:read`, `channels:join`, `channels:history`

3. **GitHub Repository**:
   - Fork or clone this repository
   - Configure repository variables and secrets
   - Enable GitHub Actions

4. **Dependencies**:
   - Python 3.11+
   - UV package manager
   - Terraform 1.9.0+

## Security Features

- **No Static Credentials**: Uses OIDC for AWS authentication
- **Encrypted Storage**: Optional KMS encryption for S3 objects
- **Atomic Writes**: Prevents partial file corruption
- **Rate Limiting**: Respects Slack API limits with intelligent backoff
- **Environment Variables**: Sensitive data stored securely
