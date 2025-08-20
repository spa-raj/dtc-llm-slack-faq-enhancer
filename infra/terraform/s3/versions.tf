terraform {
  # float within v1.x but require a reasonably new core
  required_version = ">= 1.9.0, < 2.0.0"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # float within v6.x (current major); will pick 6.9.0+ when available
      version = "~> 6.0"
    }
  }

  backend "s3" {}
}