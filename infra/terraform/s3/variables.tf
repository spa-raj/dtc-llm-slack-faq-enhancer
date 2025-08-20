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

