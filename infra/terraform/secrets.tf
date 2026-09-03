########################################################################
# Secrets Manager
#
# Every credential-shaped value from Railway's production .env gets an
# entry here, injected into ECS task definitions as `secrets` (pulled at
# container start, never baked into the image or logged). Plain
# non-credential config (ALLOWED_HOSTS, TIME_ZONE, etc.) goes as ordinary
# task-definition `environment` values in ecs.tf instead — no need to pay
# Secrets Manager's per-secret cost ($0.40/secret/mo) for things that
# aren't secret.
#
# Two secrets are generated for real right here (SECRET_KEY, ADMIN_URL) —
# the task explicitly asked for these to be real, matching production.py's
# fail-fast guards (min length 40 / not the literal "admin/").
#
# Everything else that needs a genuine third-party credential (Brevo,
# Sentry, Paystack, ...) is left as an empty string with a TODO — filling
# in a fake-looking placeholder risks it being mistaken for real and
# silently shipped. See the final report for the full TODO list.
#
# Deliberately split into TWO resource blocks (static_secrets vs
# db_cache_secrets), not one merged map: DATABASE_URL/REDIS_URL depend on
# Aurora/ElastiCache (Phase 2), while everything else (SECRET_KEY,
# ADMIN_URL, third-party placeholders, APP_DATABASE_URL) has no such
# dependency (Phase 1). Terraform's `-target` graph-walk treats any
# reference into a shared map as a dependency on everything that
# contributes to that map — merging them would silently drag Aurora +
# ElastiCache into a "Phase 1" apply. Keeping them as separate resources
# keeps the two phases' cost gates real, not just cosmetic.
########################################################################

resource "random_password" "django_secret_key" {
  length  = 64
  special = true
  # Django's SECRET_KEY generator avoids characters that are awkward in
  # shell/env-var contexts; restrict to the same safe set.
  override_special = "!@#$%^&*(-_=+)"
}

resource "random_id" "admin_url" {
  byte_length = 12
}

locals {
  admin_url = "${random_id.admin_url.hex}/"

  database_url = "postgresql://${var.db_master_username}:${urlencode(random_password.db_master.result)}@${aws_rds_cluster.main.endpoint}:${aws_rds_cluster.main.port}/${var.db_name}?sslmode=require"

  # ssl_cert_reqs is required by Celery's redis backend whenever the URL
  # scheme is rediss:// (TLS) — without it, celery-worker crashes on startup
  # with "A rediss:// URL must have parameter ssl_cert_reqs...". CERT_REQUIRED
  # is correct here (not CERT_NONE): ElastiCache Serverless presents a
  # publicly-trusted cert, so full verification is both safe and free.
  redis_url = "rediss://${aws_elasticache_serverless_cache.main.endpoint[0].address}:${aws_elasticache_serverless_cache.main.endpoint[0].port}/0?ssl_cert_reqs=CERT_REQUIRED"

  # Phase 1: no dependency on Aurora/ElastiCache.
  static_secrets = {
    SECRET_KEY = random_password.django_secret_key.result
    ADMIN_URL  = local.admin_url

    # Populated the same way as the third-party placeholders below: starts
    # "" (container reserved, no version, not injected into ECS — see the
    # for_each filter a few lines down), then filled in for real via
    # `terraform apply -var app_database_url=...` once `manage.py
    # setup_rls_role` has been run via ECS Exec against the live Aurora
    # cluster (see README "Bootstrap runbook"). Re-running apply at that
    # point both creates the version AND adds it to the running ECS
    # services automatically — same mechanism, no special-casing needed.
    APP_DATABASE_URL = var.app_database_url

    # Third-party credentials Terraform cannot invent — left blank on
    # purpose. base.py/production.py default every one of these to "" and
    # degrade gracefully (Brevo -> console email backend, Sentry -> no-op,
    # etc.), so a blank value never blocks the /api/v1/health/ check.
    BREVO_API_KEY           = var.brevo_api_key
    SENTRY_DSN              = var.sentry_dsn
    PAYSTACK_SECRET_KEY     = var.paystack_secret_key
    FLUTTERWAVE_SECRET_KEY  = var.flutterwave_secret_key
    NANGO_SECRET_KEY        = var.nango_secret_key
    NANGO_WEBHOOK_SECRET    = var.nango_webhook_secret
    TELEGRAM_BOT_TOKEN      = var.telegram_bot_token
    TELEGRAM_WEBHOOK_SECRET = var.telegram_webhook_secret
    GROQ_API_KEY            = var.groq_api_key
    POSTHOG_API_KEY         = var.posthog_api_key
    DIGITAX_APP_API_KEY     = var.digitax_app_api_key
    DIGITAX_WEBHOOK_SECRET  = var.digitax_webhook_secret
  }

  # Phase 2: depends on aws_rds_cluster.main / aws_elasticache_serverless_cache.main.
  db_cache_secrets = {
    DATABASE_URL = local.database_url
    REDIS_URL    = local.redis_url
  }

  # Which static_secrets keys currently have a real (non-"") value — used
  # below to decide which get an actual Secrets Manager *version*. Built as
  # a set of plain key strings (via nonsensitive(), which only declassifies
  # the "is it empty" boolean, never the secret content itself) because
  # Terraform forbids a sensitive-tainted expression as a for_each argument
  # — a `{k => v if v != ""}` filter over a map of sensitive values trips
  # that restriction even though the condition never leaks a value.
  static_secrets_with_value = toset([
    for k, v in local.static_secrets : k if nonsensitive(v) != ""
  ])
}

resource "aws_secretsmanager_secret" "static_app" {
  for_each = local.static_secrets
  name     = "${var.project}/${lower(each.key)}"
}

# AWS Secrets Manager's PutSecretValue rejects a literal empty string
# ("InvalidRequestException: You must provide either SecretString or
# SecretBinary") — so any placeholder still at its "" default (every
# third-party credential Terraform can't invent, plus APP_DATABASE_URL
# pre-bootstrap) gets NO version created at all, not a version with an
# empty string. The secret CONTAINER still exists (stable ARN, ready for
# `aws secretsmanager put-secret-value` later — see README). This also
# means ecs.tf must only reference secrets that actually have a version
# (see its `common_secrets` local) — referencing a version-less secret ARN
# in an ECS task definition fails the task at launch.
resource "aws_secretsmanager_secret_version" "static_app" {
  for_each      = local.static_secrets_with_value
  secret_id     = aws_secretsmanager_secret.static_app[each.value].id
  secret_string = local.static_secrets[each.value]
}

resource "aws_secretsmanager_secret" "db_cache" {
  for_each = local.db_cache_secrets
  name     = "${var.project}/${lower(each.key)}"
}

resource "aws_secretsmanager_secret_version" "db_cache" {
  for_each      = local.db_cache_secrets
  secret_id     = aws_secretsmanager_secret.db_cache[each.key].id
  secret_string = each.value
}
