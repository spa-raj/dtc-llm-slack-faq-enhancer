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

variable "attach_writer_to_roles" {
  type    = list(string)         # pass role NAMES, not ARNs
  default = ["gha-upload-raw-dev","gha-dlt-dev","gha-train-setfit-dev","gha-classify-dev"]
}

