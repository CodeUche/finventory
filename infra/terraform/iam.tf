########################################################################
# IAM — ECS task execution role (pulls image, writes logs, reads secrets)
# and ECS task role (app runtime: S3 media bucket + ECS Exec).
########################################################################

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# ─── Execution role ──────────────────────────────────────────────────────────
resource "aws_iam_role" "ecs_task_execution" {
  name               = "${var.project}-ecs-task-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_managed" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# The managed policy above covers ECR pull + CloudWatch Logs. It does NOT
# cover Secrets Manager — scope that explicitly to just the secrets this
# app needs, not "*". Split into two policy resources (static vs db/cache)
# purely so a Phase 1 apply doesn't have to reference — and thereby
# transitively create — the Phase 2 Aurora/ElastiCache resources; IAM
# policies are free, so there's no cost reason to merge them.
data "aws_iam_policy_document" "ecs_task_execution_static_secrets" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [for s in aws_secretsmanager_secret.static_app : s.arn]
  }
}

resource "aws_iam_role_policy" "ecs_task_execution_static_secrets" {
  name   = "${var.project}-ecs-exec-static-secrets"
  role   = aws_iam_role.ecs_task_execution.id
  policy = data.aws_iam_policy_document.ecs_task_execution_static_secrets.json
}

data "aws_iam_policy_document" "ecs_task_execution_db_cache_secrets" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [for s in aws_secretsmanager_secret.db_cache : s.arn]
  }
}

resource "aws_iam_role_policy" "ecs_task_execution_db_cache_secrets" {
  name   = "${var.project}-ecs-exec-db-cache-secrets"
  role   = aws_iam_role.ecs_task_execution.id
  policy = data.aws_iam_policy_document.ecs_task_execution_db_cache_secrets.json
}

# ─── Task role (application runtime identity) ───────────────────────────────
resource "aws_iam_role" "ecs_task" {
  name               = "${var.project}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

# S3 media bucket access — scoped to exactly this bucket, nothing else.
# This also removes the need for static S3_ACCESS_KEY_ID/SECRET in
# production.py: boto3's default credential chain picks up this role's
# temporary credentials automatically inside the container.
data "aws_iam_policy_document" "ecs_task_s3" {
  statement {
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.media.arn}/*"]
  }
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.media.arn]
  }
}

resource "aws_iam_role_policy" "ecs_task_s3" {
  name   = "${var.project}-ecs-task-s3"
  role   = aws_iam_role.ecs_task.id
  policy = data.aws_iam_policy_document.ecs_task_s3.json
}

# ECS Exec (used once, operationally, to run `manage.py setup_rls_role`
# against the brand-new Aurora cluster without ever exposing it publicly —
# see README "Bootstrap runbook"). Cheap to leave enabled permanently: it
# only works when someone with ecs:ExecuteCommand IAM permission invokes it.
data "aws_iam_policy_document" "ecs_task_exec" {
  statement {
    actions = [
      "ssmmessages:CreateControlChannel",
      "ssmmessages:CreateDataChannel",
      "ssmmessages:OpenControlChannel",
      "ssmmessages:OpenDataChannel",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "ecs_task_exec" {
  name   = "${var.project}-ecs-task-exec"
  role   = aws_iam_role.ecs_task.id
  policy = data.aws_iam_policy_document.ecs_task_exec.json
}
