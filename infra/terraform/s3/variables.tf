variable "aws_region" {
  type    = string
  default = "ap-south-1"
}

variable "bucket_name" {
  type = string
}

variable "use_kms" {
  type    = bool
  default = false
}

variable "kms_key_arn" {
  type    = string
  default = ""
}

variable "raw_ia_days" {
  type    = number
  default = 30
}

variable "raw_glacier_days" {
  type    = number
  default = 180
}

variable "bronze_ia_days" {
  type    = number
  default = 30
}

variable "silver_ia_days" {
  type    = number
  default = 30
}

variable "enable_versioning" {
  type    = bool
  default = true
}

variable "tags" {
  type = map(string)
  default = {
    project = "dtc-llm-hackathon"
  }
}

variable "create_writer_policy" {
  type    = bool
  default = true
}

variable "writer_principal_arn" {
  type    = string
  default = ""
}

variable "github_repo" {
  type        = string
  description = "GitHub repository in format owner/repo"
  default     = "sparsh-raj/dtc-llm-slack-faq-enhancer"
}

variable "github_environment" {
  type        = string
  description = "GitHub environment name"
  default     = "dev"
}

variable "slack_s3_writer_role_name" {
  type        = string
  description = "Name of the IAM role for Slack S3 writer"
  default     = "gha-dlt-ingestion-dev"
}

variable "create_slack_writer_role" {
  type        = bool
  description = "Whether to create the Slack S3 writer IAM role"
  default     = true
}