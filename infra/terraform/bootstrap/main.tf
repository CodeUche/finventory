########################################################################
# Bootstrap: Terraform state bucket
#
# Chicken-and-egg fix: the main config (../) uses an S3 backend, but that
# bucket has to exist before `terraform init` can point at it. This tiny
# module is applied ONCE, with Terraform's default local backend, purely
# to create the state bucket + turn on versioning/encryption/public-access
# block. After this apply, `cd ../` and run `terraform init` there — it
# points at the bucket this creates.
#
# This bootstrap module's own state (a few KB, describing one S3 bucket)
# is intentionally left as a local `terraform.tfstate` file in this
# directory, committed nowhere (see .gitignore) — re-running this apply
# is a rare, deliberate action, so a remote backend for it would be
# over-engineering. If it's ever lost, the bucket already exists in AWS
# and can be re-imported.
########################################################################

terraform {
  required_version = ">= 1.15.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile
}

variable "aws_region" {
  type    = string
  default = "eu-west-1"
}

variable "aws_profile" {
  type    = string
  default = "audity-migration"
}

variable "state_bucket_name" {
  description = "Globally-unique S3 bucket name for Terraform state."
  type        = string
}

resource "aws_s3_bucket" "tf_state" {
  bucket = var.state_bucket_name

  # Deliberately no force_destroy — this bucket holds the only copy of
  # infrastructure state; accidental `terraform destroy` on it must fail
  # rather than silently wipe history.
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "tf_state" {
  bucket = aws_s3_bucket.tf_state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tf_state" {
  bucket = aws_s3_bucket.tf_state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tf_state" {
  bucket                  = aws_s3_bucket.tf_state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

output "state_bucket_name" {
  value = aws_s3_bucket.tf_state.id
}
