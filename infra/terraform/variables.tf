variable "aws_region" {
  description = "AWS region. eu-west-1 chosen over af-south-1: ~20% cheaper compute, ~70% cheaper egress, comparable real-world latency to Nigeria via existing submarine-cable routing through Europe."
  type        = string
  default     = "eu-west-1"
}

variable "aws_profile" {
  description = "Local AWS CLI profile to use."
  type        = string
  default     = "audity-migration"
}

variable "environment" {
  description = "Logical environment name, used in resource naming/tags."
  type        = string
  default     = "prod"
}

variable "project" {
  description = "Short project name, used as a naming prefix on every resource."
  type        = string
  default     = "audity"
}

variable "account_id" {
  description = "AWS account ID (used to build globally-unique bucket names)."
  type        = string
  default     = "222907083438"
}

# ─── Networking ────────────────────────────────────────────────────────────
variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "azs" {
  description = "Two AZs — enough for ECS/ALB/Aurora HA-readiness without a third AZ's worth of subnets to manage."
  type        = list(string)
  default     = ["eu-west-1a", "eu-west-1b"]
}

variable "public_subnet_cidrs" {
  type    = list(string)
  default = ["10.20.0.0/24", "10.20.1.0/24"]
}

variable "private_app_subnet_cidrs" {
  description = "Private subnets for ECS tasks."
  type        = list(string)
  default     = ["10.20.10.0/24", "10.20.11.0/24"]
}

variable "private_data_subnet_cidrs" {
  description = "Private subnets for Aurora + ElastiCache."
  type        = list(string)
  default     = ["10.20.20.0/24", "10.20.21.0/24"]
}

# ─── ECS / compute ─────────────────────────────────────────────────────────
variable "container_port" {
  type    = number
  default = 8000
}

variable "api_cpu" {
  description = "Fargate task CPU units for the api service (256 = 0.25 vCPU, the smallest Fargate task size)."
  type        = number
  default     = 256
}

variable "api_memory" {
  description = "Fargate task memory (MB) for the api service."
  type        = number
  default     = 512
}

variable "api_min_count" {
  type    = number
  default = 1
}

variable "api_max_count" {
  description = "Autoscaling ceiling for the api service."
  type        = number
  default     = 4
}

variable "worker_cpu" {
  type    = number
  default = 256
}

variable "worker_memory" {
  type    = number
  default = 512
}

variable "worker_desired_count" {
  description = "Celery worker task count. Kept fixed at 1 for now — no built-in ECS metric for Celery queue depth; autoscaling this would need a custom CloudWatch metric, deferred as a follow-up."
  type        = number
  default     = 1
}

variable "beat_cpu" {
  type    = number
  default = 256
}

variable "beat_memory" {
  type    = number
  default = 512
}

# ─── Database (Aurora Serverless v2) ───────────────────────────────────────
variable "db_name" {
  type    = string
  default = "finventory"
}

variable "db_master_username" {
  type    = string
  default = "postgres"
}

variable "aurora_engine_version" {
  description = "Matches the Postgres major version already in use (Dockerfile installs postgresql-client-18 to match Railway's server)."
  type        = string
  default     = "18.4"
}

variable "aurora_min_acu" {
  description = "Minimum Aurora Capacity Units. 0.5 is the lowest the engine allows — the whole point of Serverless v2 for a pre-revenue app."
  type        = number
  default     = 0.5
}

variable "aurora_max_acu" {
  type    = number
  default = 4
}

variable "aurora_multi_az" {
  description = "Whether to add a reader instance in a second AZ for HA. Defaults to false (single-AZ) per the cost-ceiling instruction — see README for the cost math. Flip to true once revenue justifies ~doubling Aurora compute cost."
  type        = bool
  default     = false
}

# ─── Cache (ElastiCache Serverless for Redis) ──────────────────────────────
variable "redis_max_storage_gb" {
  description = "Cap on ElastiCache Serverless data storage — prevents runaway cost from a cache/broker leak."
  type        = number
  default     = 2
}

variable "redis_max_ecpu_per_second" {
  description = "Cap on ElastiCache Serverless compute (ECPUs/sec) — same cost-ceiling reasoning."
  type        = number
  default     = 2000
}

# ─── Secrets requiring a real value the user must supply ───────────────────
# All default to "" (safe — base.py already defaults these to "" and the app
# degrades gracefully: Brevo falls back to console email backend, Sentry
# simply doesn't init, etc.). None of these gate the /api/v1/health/ check.
variable "brevo_api_key" {
  type      = string
  default   = ""
  sensitive = true
}

variable "sentry_dsn" {
  type      = string
  default   = ""
  sensitive = true
}

variable "default_from_email" {
  type    = string
  default = ""
}

variable "paystack_secret_key" {
  type      = string
  default   = ""
  sensitive = true
}

variable "paystack_public_key" {
  type    = string
  default = ""
}

variable "flutterwave_secret_key" {
  type      = string
  default   = ""
  sensitive = true
}

variable "nango_secret_key" {
  type      = string
  default   = ""
  sensitive = true
}

variable "nango_webhook_secret" {
  type      = string
  default   = ""
  sensitive = true
}

variable "telegram_bot_token" {
  type      = string
  default   = ""
  sensitive = true
}

variable "telegram_webhook_secret" {
  type      = string
  default   = ""
  sensitive = true
}

variable "groq_api_key" {
  type      = string
  default   = ""
  sensitive = true
}

variable "posthog_api_key" {
  type      = string
  default   = ""
  sensitive = true
}

variable "digitax_app_api_key" {
  type      = string
  default   = ""
  sensitive = true
}

variable "digitax_webhook_secret" {
  type      = string
  default   = ""
  sensitive = true
}

variable "app_database_url" {
  description = "The audity_app (RLS-restricted) Postgres connection string. Stays empty until `manage.py setup_rls_role` has been run once via ECS Exec against the live Aurora cluster — see README 'Bootstrap runbook'. Until then the app runs on DATABASE_URL (superuser, RLS bypassed) so the health check and initial bring-up aren't blocked on a manual step."
  type        = string
  default     = ""
  sensitive   = true
}

variable "frontend_url" {
  description = "Existing Vercel frontend URL — unchanged by this migration. Low-stakes: base.py notes verify-email now uses BACKEND_URL directly, this is 'kept for reference'. Left blank by default — set it if you have a canonical production Vercel domain."
  type        = string
  default     = ""
}

variable "support_ticket_email" {
  type    = string
  default = "support@auditytechnologies.com"
}
