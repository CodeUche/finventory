########################################################################
# ECS Fargate — 3 services from 1 image (api / worker / beat), mirroring
# exactly how Railway splits the same Dockerfile today via different
# "start commands". Container Insights left OFF (default) — standard
# ECS + CloudWatch Logs metrics are enough at this stage, and Insights
# adds its own per-metric CloudWatch cost; Sentry + the existing
# self-hosted Grafana stack remain the primary dashboards.
########################################################################

variable "image_tag" {
  description = "ECR image tag to deploy. The repo is IMMUTABLE (see ecr.tf), so each new build needs a new tag — e.g. a git SHA in the eventual CI job (Phase 6, not part of this session). Bootstrap value below is pushed once, manually, during this session's bring-up."
  type        = string
  default     = "bootstrap-v4"
}

resource "aws_ecs_cluster" "main" {
  name = "${var.project}-cluster"
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 100
  }
}

resource "aws_security_group" "ecs_tasks" {
  name        = "${var.project}-ecs-tasks-sg"
  description = "ECS tasks: ingress from ALB on the app port only, egress open (NAT-routed)"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "App port from ALB"
    from_port       = var.container_port
    to_port         = var.container_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-ecs-tasks-sg" }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.project}/api"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${var.project}/worker"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "beat" {
  name              = "/ecs/${var.project}/beat"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "migrate" {
  name              = "/ecs/${var.project}/migrate"
  retention_in_days = 14
}

locals {
  # Plain (non-secret) runtime config shared by all three services.
  # ALLOWED_HOSTS/BACKEND_URL point at the raw ALB DNS name for now — a
  # real domain (api.audity.africa) + HTTPS listener is Phase 8 (DNS
  # cutover), out of scope for this session.
  common_environment = [
    { name = "DJANGO_SETTINGS_MODULE", value = "config.settings.production" },
    { name = "DEBUG", value = "False" },
    # No HTTPS listener on the ALB yet (Phase 8 — needs a real domain for
    # an ACM cert). Without this, SECURE_SSL_REDIRECT's default True 301s
    # every request, including the ALB health check, to a nonexistent
    # HTTPS endpoint. Remove this line (or flip to "True") once Phase 8's
    # HTTPS listener + domain are in place.
    { name = "SECURE_SSL_REDIRECT", value = "False" },
    # ALB health checks hit the task's private IP directly (Host: <ip>:8000,
    # not the ALB's DNS name), so the DNS name alone gets every health check
    # rejected as DisallowedHost. Wildcard is standard practice for an
    # ALB-fronted app in a private subnet: the security groups (ALB-only
    # ingress on the container port, no public IP on the tasks) are the
    # real access boundary here, not the Host header. Revisit if/when a
    # real domain + HTTPS listener replaces the raw ALB DNS name (Phase 8).
    { name = "ALLOWED_HOSTS", value = "${aws_lb.main.dns_name},*" },
    { name = "TIME_ZONE", value = "Africa/Lagos" },
    { name = "CORS_ALLOWED_ORIGINS", value = var.frontend_url != "" ? var.frontend_url : "http://localhost:3000" },
    { name = "CSRF_TRUSTED_ORIGINS", value = var.frontend_url != "" ? var.frontend_url : "http://localhost:3000" },
    { name = "USE_S3", value = "True" },
    { name = "S3_BUCKET_NAME", value = aws_s3_bucket.media.id },
    { name = "S3_REGION", value = var.aws_region },
    { name = "FRONTEND_URL", value = var.frontend_url },
    { name = "BACKEND_URL", value = "http://${aws_lb.main.dns_name}" },
    { name = "SUPPORT_TICKET_EMAIL", value = var.support_ticket_email },
    { name = "DEFAULT_FROM_EMAIL", value = var.default_from_email },
    { name = "PAYSTACK_PUBLIC_KEY", value = var.paystack_public_key },
    { name = "POSTHOG_HOST", value = "https://us.i.posthog.com" },
  ]

  # Only secrets that actually have a version get injected — ECS fails a
  # task at launch ("ResourceInitializationError") if it's told to resolve
  # a secret ARN with no version yet. That's exactly the state of every
  # still-blank third-party credential and APP_DATABASE_URL pre-bootstrap
  # (see secrets.tf) — they simply aren't passed to the container, and
  # base.py/production.py's own "" defaults take over identically to if
  # the var were never set. A later `terraform apply` picks them up
  # automatically once a real value lands in Secrets Manager.
  common_secrets = concat(
    [for k, v in aws_secretsmanager_secret_version.static_app : { name = k, valueFrom = aws_secretsmanager_secret.static_app[k].arn }],
    [for k, v in aws_secretsmanager_secret_version.db_cache : { name = k, valueFrom = aws_secretsmanager_secret.db_cache[k].arn }],
  )

  image = "${aws_ecr_repository.backend.repository_url}:${var.image_tag}"
}

# ─── One-off migration task ────────────────────────────────────────────────
# Structural fix for a real concurrent-migrate race: the Dockerfile's
# default CMD runs `python migrate.py` on every cold start of the `api`
# container. With api autoscaling 1→4 (aws_appautoscaling_target.api
# below) or during any rolling deployment where old+new tasks briefly
# overlap, multiple containers can call migrate.py against the same Aurora
# database at once — reproduced in testing as Postgres catalog-level
# errors (e.g. "duplicate key value violates unique constraint
# pg_type_typname_nsp_index") from concurrent DDL, not just an
# application-level migration bug.
#
# Fix: migrations run exactly once per deploy, as a standalone one-off
# ECS task (RunTask, not a long-lived service) — see README "Deploy
# runbook". `api`'s own container command below explicitly skips
# migrate.py/setup_periodic_tasks and goes straight to gunicorn, so no
# service container ever runs migrate.py again, at any scale.
resource "aws_ecs_task_definition" "migrate" {
  family                   = "${var.project}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name        = "migrate"
    image       = local.image
    essential   = true
    command     = ["sh", "-c", "python migrate.py && python manage.py setup_periodic_tasks"]
    environment = local.common_environment
    secrets     = local.common_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.migrate.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "migrate"
      }
    }
  }])
}

# ─── api service ─────────────────────────────────────────────────────────
resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "api"
    image     = local.image
    essential = true
    # Explicit override — skips the Dockerfile default CMD's migrate.py/
    # setup_periodic_tasks entirely (see aws_ecs_task_definition.migrate
    # above for why). collectstatic and the optional createsuperuser stay
    # here: they're local-filesystem/idempotent-row operations, safe to
    # repeat per task, and collectstatic specifically MUST run per-task
    # since Fargate tasks don't share storage — each container needs its
    # own populated staticfiles dir for Whitenoise to serve from.
    command      = ["sh", "-c", "(python manage.py collectstatic --no-input --clear 2>/dev/null || true) && if [ -n \"$DJANGO_SUPERUSER_EMAIL\" ] && [ -n \"$DJANGO_SUPERUSER_PASSWORD\" ]; then python manage.py createsuperuser --no-input --email \"$DJANGO_SUPERUSER_EMAIL\" 2>/dev/null || true; fi && gunicorn config.wsgi:application --bind 0.0.0.0:${var.container_port} --workers 2 --worker-class sync --worker-tmp-dir /dev/shm --access-logfile - --error-logfile - --log-level info --timeout 120"]
    portMappings = [{ containerPort = var.container_port, protocol = "tcp" }]
    environment  = local.common_environment
    secrets      = local.common_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.api.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "api"
      }
    }
  }])
}

resource "aws_ecs_service" "api" {
  name            = "${var.project}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_min_count
  launch_type     = "FARGATE"

  # ECS Exec enabled for the one-time `setup_rls_role` bootstrap step (see
  # README) — otherwise unused, and free unless someone actually execs in.
  enable_execute_command = true

  network_configuration {
    subnets          = aws_subnet.private_app[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = var.container_port
  }

  depends_on = [aws_lb_listener.http]

  lifecycle {
    ignore_changes = [desired_count] # let autoscaling own this after the initial apply
  }
}

resource "aws_appautoscaling_target" "api" {
  max_capacity       = var.api_max_count
  min_capacity       = var.api_min_count
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "api_request_count" {
  name               = "${var.project}-api-request-count"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.api.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ALBRequestCountPerTarget"
      resource_label         = "${aws_lb.main.arn_suffix}/${aws_lb_target_group.api.arn_suffix}"
    }
    target_value       = 500 # requests/min/target before scaling out — generous headroom for a 0.25 vCPU task at pre-launch traffic
    scale_in_cooldown  = 120
    scale_out_cooldown = 60
  }
}

# ─── celery worker (Fargate Spot) ──────────────────────────────────────────
resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.project}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name        = "worker"
    image       = local.image
    essential   = true
    command     = ["sh", "-c", "celery -A config.celery worker --loglevel=info --concurrency=2"]
    environment = local.common_environment
    secrets     = local.common_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.worker.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "worker"
      }
    }
  }])
}

resource "aws_ecs_service" "worker" {
  name            = "${var.project}-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.worker_desired_count

  capacity_provider_strategy {
    capacity_provider = "FARGATE_SPOT"
    weight            = 100
  }

  network_configuration {
    subnets          = aws_subnet.private_app[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }
}

# ─── celery beat (fixed, on-demand — the scheduler cannot scale to zero
# and must not run more than once, so it also must NOT be on Spot) ─────────
resource "aws_ecs_task_definition" "beat" {
  family                   = "${var.project}-beat"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.beat_cpu
  memory                   = var.beat_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name        = "beat"
    image       = local.image
    essential   = true
    command     = ["sh", "-c", "celery -A config.celery beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler"]
    environment = local.common_environment
    secrets     = local.common_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.beat.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "beat"
      }
    }
  }])
}

resource "aws_ecs_service" "beat" {
  name            = "${var.project}-beat"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.beat.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private_app[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }
}
