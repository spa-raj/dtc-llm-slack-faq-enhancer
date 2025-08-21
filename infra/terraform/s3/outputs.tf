output "bucket_name" {
  value = aws_s3_bucket.slack.bucket
}

output "bucket_arn" {
  value = aws_s3_bucket.slack.arn
}

output "writer_policy_arn" {
  value = try(aws_iam_policy.writer[0].arn, null)
}

output "slack_s3_writer_role_arn" {
  value       = try(aws_iam_role.slack_s3_writer[0].arn, null)
  description = "ARN of the IAM role for Slack S3 writer"
}

output "slack_s3_writer_role_name" {
  value       = try(aws_iam_role.slack_s3_writer[0].name, null)
  description = "Name of the IAM role for Slack S3 writer"
}