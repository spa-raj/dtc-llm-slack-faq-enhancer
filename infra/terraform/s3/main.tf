resource "aws_s3_bucket" "slack" {
  bucket = var.bucket_name
  tags   = var.tags
}

resource "aws_s3_bucket_public_access_block" "slack" {
  bucket                  = aws_s3_bucket.slack.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "slack" {
  bucket = aws_s3_bucket.slack.id
  rule {
    object_ownership = "BucketOwnerPreferred"
  }
}

resource "aws_s3_bucket_versioning" "slack" {
  bucket = aws_s3_bucket.slack.id
  versioning_configuration {
    status = var.enable_versioning ? "Enabled" : "Suspended"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "slack" {
  bucket = aws_s3_bucket.slack.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.use_kms ? "aws:kms" : "AES256"
      kms_master_key_id = var.use_kms ? var.kms_key_arn : null
    }
  }
}

data "aws_iam_policy_document" "deny_insecure_transport" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    resources = [
      aws_s3_bucket.slack.arn,
      "${aws_s3_bucket.slack.arn}/*"
    ]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "slack" {
  bucket = aws_s3_bucket.slack.id
  policy = data.aws_iam_policy_document.deny_insecure_transport.json
}

resource "aws_s3_bucket_lifecycle_configuration" "slack" {
  bucket = aws_s3_bucket.slack.id

  rule {
    id     = "raw-transitions"
    status = "Enabled"
    filter {
      prefix = "raw/slack/"
    }
    transition {
      days          = var.raw_ia_days
      storage_class = "STANDARD_IA"
    }
    transition {
      days          = var.raw_glacier_days
      storage_class = "GLACIER"
    }
  }

  rule {
    id     = "bronze-transitions"
    status = "Enabled"
    filter {
      prefix = "bronze/slack/"
    }
    transition {
      days          = var.bronze_ia_days
      storage_class = "STANDARD_IA"
    }
  }

  rule {
    id     = "silver-transitions"
    status = "Enabled"
    filter {
      prefix = "silver/slack/"
    }
    transition {
      days          = var.silver_ia_days
      storage_class = "STANDARD_IA"
    }
  }
}

data "aws_iam_policy_document" "writer" {
  statement {
    sid       = "ListBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.slack.arn]
  }

  statement {
    sid       = "RW"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.slack.arn}/*"]
  }
}

resource "aws_iam_policy" "writer" {
  count       = var.create_writer_policy ? 1 : 0
  name        = "${var.bucket_name}-writer"
  description = "RW policy for Slack data lake bucket"
  policy      = data.aws_iam_policy_document.writer.json
}