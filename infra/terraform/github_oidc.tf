########################################################################
# GitHub Actions -> AWS via OIDC
#
# Why OIDC and not access keys: no long-lived AWS credentials are stored
# in GitHub at all. Actions exchanges a short-lived signed token for
# temporary STS credentials, so there is nothing to leak or rotate. The
# role ARN referenced by the workflow is not a secret.
#
# Why this exists at all: image builds cannot run on the developer
# machine — Avast's TLS interception breaks HTTPS fetches inside the
# Docker build (the postgresql-client apt key step fails with curl 60).
# Building in Actions sidesteps that permanently and is where Phase 6 of
# the migration plan puts builds anyway.
#
# Trust is scoped to this repository and to specific branches, so a fork
# or an unrelated branch cannot assume the role.
########################################################################

variable "github_repository" {
  description = "owner/repo allowed to assume the deploy role."
  type        = string
  default     = "CodeUche/finventory"
}

variable "github_deploy_refs" {
  description = "Git refs permitted to assume the deploy role."
  type        = list(string)
  default     = ["refs/heads/main", "refs/heads/infra/aws-migration"]
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 0 : 1
  url   = "https://token.actions.githubusercontent.com"
}

variable "create_github_oidc_provider" {
  description = "False if an OIDC provider for GitHub already exists in the account."
  type        = bool
  default     = true
}

resource "aws_iam_openid_connect_provider" "github" {
  count           = var.create_github_oidc_provider ? 1 : 0
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  # AWS verifies GitHub's certificate chain itself; the thumbprint is kept
  # because the API still expects the field to be populated.
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

locals {
  github_oidc_arn = var.create_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github[0].arn
}

resource "aws_iam_role" "github_deploy" {
  name = "${var.project}-github-deploy"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = local.github_oidc_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = [
            for r in var.github_deploy_refs : "repo:${var.github_repository}:ref:${r}"
          ]
        }
      }
    }]
  })
}

# Least privilege: push images to this one ECR repo, and roll the three
# ECS services. Deliberately no blanket ecs:* or iam:*.
resource "aws_iam_role_policy" "github_deploy" {
  name = "${var.project}-github-deploy"
  role = aws_iam_role.github_deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*" # this action does not support resource scoping
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:CompleteLayerUpload",
          "ecr:InitiateLayerUpload",
          "ecr:PutImage",
          "ecr:UploadLayerPart",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
        ]
        Resource = aws_ecr_repository.backend.arn
      },
      {
        Effect = "Allow"
        Action = [
          "ecs:DescribeServices",
          "ecs:DescribeTaskDefinition",
          "ecs:RegisterTaskDefinition",
          "ecs:UpdateService",
          "ecs:RunTask",
          "ecs:DescribeTasks",
        ]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [aws_iam_role.ecs_task.arn, aws_iam_role.ecs_task_execution.arn]
      },
    ]
  })
}

output "github_deploy_role_arn" {
  description = "Reference this in the GitHub Actions workflow (not a secret)."
  value       = aws_iam_role.github_deploy.arn
}
