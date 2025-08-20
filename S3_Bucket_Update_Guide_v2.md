# S3 Bucket Update Guide (v2) — Terraform + GitHub Actions

_This guide converts the S3 infra to the new MVP architecture with **two data flows**:_
1. **Slack API → dlt → S3** (ingestion: writes raw JSON to S3)
2. **S3 → dlt → Qdrant** (processing: reads raw, processes, stores in vector DB)

_No bronze/silver/gold Parquet layers. It also updates the Terraform GitHub workflow to match._

## What changes (high level)

- Keep **only raw Slack JSON** in S3 under:  
  `s3://<DATA_BUCKET>/raw/slack/<course_id>/year=YYYY/month=MM/day=DD/<YYYY-MM-DD>.json`
- Remove Parquet data-lake layers and lifecycle rules for **bronze/silver**.
- **Keep the writer policy** for the Slack API → S3 ingestion flow (scoped to `raw/slack/*` prefix only).
- Terraform still enforces: block public access, versioning, server-side encryption, and **DenyInsecureTransport**.

---

## 1) Terraform changes (S3)

Make these edits in `infra/terraform/s3`:

### 1.1 `variables.tf` — remove unused inputs
Delete the bronze/silver variables; keep the raw-only knobs and writer policy enabled.

```diff
- variable "bronze_ia_days" { type = number, default = 30 }
- variable "silver_ia_days" { type = number, default = 30 }

# Keep the writer policy enabled for Slack API → S3 ingestion
+ variable "create_writer_policy"  { type = bool, default = true }
```

### 1.2 `main.tf` — keep bucket + policy + encryption; trim lifecycle to **raw only**

Leave these blocks as-is (no changes needed):
- `aws_s3_bucket`, `aws_s3_bucket_public_access_block`, `aws_s3_bucket_ownership_controls`
- `aws_s3_bucket_versioning`, `aws_s3_bucket_server_side_encryption_configuration`
- `data.aws_iam_policy_document.deny_insecure_transport` and `aws_s3_bucket_policy`

**Replace** the lifecycle configuration with this **single** rule and **remove** bronze/silver rules:

```hcl
resource "aws_s3_bucket_lifecycle_configuration" "slack" {
  bucket = aws_s3_bucket.slack.id

  rule {
    id     = "raw-transitions"
    status = "Enabled"
    filter { prefix = "raw/slack/" }
    transition { days = var.raw_ia_days      storage_class = "STANDARD_IA" }
    transition { days = var.raw_glacier_days storage_class = "GLACIER" }
  }
}
```

**Keep the writer policy** but scope it to only write to `raw/slack/*` prefix:

```hcl
data "aws_iam_policy_document" "writer" {
  statement {
    sid     = "ListRawPrefix"
    effect  = "Allow"
    actions = ["s3:ListBucket"]
    resources = [aws_s3_bucket.slack.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["raw/slack/*"]
    }
  }

  statement {
    sid     = "WriteRawOnly"
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"]
    resources = ["${aws_s3_bucket.slack.arn}/raw/slack/*"]
  }
}

resource "aws_iam_policy" "writer" {
  count       = var.create_writer_policy ? 1 : 0
  name        = "${aws_s3_bucket.slack.id}-writer"
  description = "Write policy for raw Slack data ingestion"
  policy      = data.aws_iam_policy_document.writer.json
}

# Attach to ingestion roles only
resource "aws_iam_role_policy_attachment" "writer_attach" {
  for_each   = var.create_writer_policy ? toset(var.attach_writer_to_roles) : toset([])
  role       = each.value
  policy_arn = aws_iam_policy.writer[0].arn
}
```

### 1.3 `outputs.tf` — keep the writer policy output
Keep the writer policy output since we're using it:

```hcl
output "writer_policy_arn" {
  value = try(aws_iam_policy.writer[0].arn, null)
  description = "ARN of the writer policy for raw data ingestion"
}
```

---

## 2) GitHub Actions — Terraform workflow updates

Open `.github/workflows/01-terraform-deploy.yml` and make these edits.

### 2.1 Keep writer-policy for ingestion
Keep the writer policy checks since we need it for Slack API → S3 ingestion:

```yaml
 env:
   TF_VERSION: '1.12.2'
   WORKING_DIR: 'infra/terraform/s3'
   BUCKET_DATA: ${{ vars.BUCKET_DATA }}
   BUCKET_STATE: ${{ vars.BUCKET_STATE }}
   STATE_PREFIX: ${{ vars.STATE_PREFIX }}
   AWS_REGION: ${{ vars.AWS_REGION }}
   AWS_ACCOUNT_ID: ${{ vars.AWS_ACCOUNT_ID }}
   TERRAFORM_ROLE_NAME: ${{ vars.TERRAFORM_ROLE_NAME }}
   WRITER_POLICY_ARN: arn:aws:iam::${{ vars.AWS_ACCOUNT_ID }}:policy/${{ vars.BUCKET_DATA }}-writer
```

Keep the post-apply checks as they are (no changes needed) since we still have the writer policy:

```yaml
      - name: Post-apply — verify remote state & IAM
        if: ${{ inputs.action == 'apply' || github.event.inputs.action == 'apply' }}
        run: |
          set -euo pipefail
          echo "State object should exist now:"
          aws s3api head-object \
            --bucket "${{ env.BUCKET_STATE }}" \
            --key "${{ env.STATE_PREFIX }}/terraform.tfstate"

          echo "Writer policy should exist:"
          aws iam get-policy --policy-arn "${{ env.WRITER_POLICY_ARN }}"

          echo "Writer policy attachments (roles that have it):"
          aws iam list-entities-for-policy \
            --policy-arn "${{ env.WRITER_POLICY_ARN }}" \
            --query "PolicyRoles[].RoleName" \
            --output table
```

No other changes are required: `terraform init/plan/apply` flags and the remote-state backend remain correct.

---

## 3) Apply & validate

From repo root:

```bash
cd infra/terraform/s3
terraform init \
  -backend-config="bucket=${BUCKET_STATE}" \
  -backend-config="key=${STATE_PREFIX}/terraform.tfstate" \
  -backend-config="region=${AWS_REGION}"

terraform plan  -var="bucket_name=${BUCKET_DATA}" -var="aws_region=${AWS_REGION}" -out=tfplan
terraform apply -auto-approve -var="bucket_name=${BUCKET_DATA}" -var="aws_region=${AWS_REGION}"
```

Post-apply checks:

```bash
# Lifecycle should only show "raw-transitions"
aws s3api get-bucket-lifecycle-configuration --bucket "${BUCKET_DATA}"

# Policy should deny insecure transport
aws s3api get-bucket-policy --bucket "${BUCKET_DATA}" | jq -r .Policy
```

---

## 4) Sanity check: expected S3 layout

Only raw JSON is kept (no bronze/silver/gold paths):

```
s3://$BUCKET_DATA/raw/slack/<course_id>/year=YYYY/month=MM/day=DD/<YYYY-MM-DD>.json
```

Quick list to verify today’s partition:

```bash
aws s3 ls "s3://${BUCKET_DATA}/raw/slack/<course_id>/year=$(date -u +%Y)/month=$(date -u +%m)/day=$(date -u +%d)/" --recursive | head
```

---

## 5) Notes for the pipeline

- **Data Flow 1**: Slack API → dlt → S3 (`raw/slack/*`) - requires writer policy for ingestion
- **Data Flow 2**: S3 → dlt → Qdrant - reads raw from S3, **scrubs PII**, calls the LLM to label questions, embeds, and **upserts to Qdrant**
- The writer policy is scoped to only allow writes to `raw/slack/*` prefix, following least-privilege principles
- If you later re-introduce bronze/silver/gold layers, update the writer policy permissions accordingly

---

### Done
You can now run the Terraform workflow (`plan` or `apply`) without any writer-policy assumptions and with a raw‑only lifecycle on the data bucket.
