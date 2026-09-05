terraform {
  required_version = ">= 1.15.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Native S3 state locking (Terraform >= 1.11) — no DynamoDB lock table needed.
  # bucket/region/key are set via -backend-config or backend.hcl at `init` time
  # (kept out of this file so the bucket name isn't hardcoded twice); see
  # infra/terraform/README.md for the exact init command.
  backend "s3" {
    use_lockfile = true
    encrypt      = true
  }
}
