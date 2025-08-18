output "bucket_name" {
  value = aws_s3_bucket.slack.bucket
}

output "bucket_arn" {
  value = aws_s3_bucket.slack.arn
}

output "writer_policy_arn" {
  value       = aws_iam_policy.writer.arn
  description = "Writer policy ARN when created by Terraform"
}
