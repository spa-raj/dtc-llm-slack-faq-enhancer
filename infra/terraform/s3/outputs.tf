output "bucket_name" {
  value = aws_s3_bucket.slack.bucket
}

output "bucket_arn" {
  value = aws_s3_bucket.slack.arn
}

output "writer_policy_arn" {
  value       = try(aws_iam_policy.writer[0].arn, null)
  description = "ARN of the writer policy for raw data ingestion"
}
