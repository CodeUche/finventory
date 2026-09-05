########################################################################
# Redis: TWO separate resources, not one — a real bug caught in staging.
#
# ElastiCache Serverless for Redis speaks Redis Cluster protocol even
# though it exposes a single endpoint. django_redis's cache only ever does
# single-key GET/SET, so that's invisible there — but Celery's kombu Redis
# transport issues multi-key MULTI/EXEC operations on worker startup
# ("mingle" bootstep), which Cluster mode rejects outright: every
# celery-worker task crashed on boot with "CROSSSLOT Keys in request
# don't hash to the same slot" until this split existed.
#
# So: ElastiCache Serverless stays exactly as originally designed for the
# django_redis cache only (scale-to-near-zero, single-key ops only, cost
# per variables.tf's caps) — aws_elasticache_serverless_cache.main below.
# Celery's broker/result-backend gets its own small, plain (non-cluster)
# ElastiCache node — aws_elasticache_replication_group.celery below,
# num_cache_clusters=1 (no failover/replica — same "smallest thing that
# works" reasoning as everywhere else in this budget). This is the one
# other fixed-cost line item in this design besides the NAT Gateway,
# ~$12-15/mo, still trivial against the $500 budget.
########################################################################

resource "aws_security_group" "redis" {
  name        = "${var.project}-redis-sg"
  description = "Allow Redis only from the ECS task security group"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Redis from ECS tasks"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-redis-sg" }
}


# ─── Redis credentials ──────────────────────────────────────────────────────
# Neither cache required authentication before this. Both sit in private
# subnets reachable only from the ECS task security group, so this is defence
# in depth rather than a perimeter fix — an attacker inside a task already
# holds DATABASE_URL. It matters because the Celery broker can enqueue any of
# ~30 registered tasks (payslips, FIRS e-invoicing submissions, depreciation
# postings), so unauthenticated write access to it is a task-injection
# primitive, and because a future security-group change could widen reach.
#
# Alphanumeric only. ElastiCache rejects several punctuation characters in
# AUTH tokens in practice (the documented exclusions are narrower than what
# the API actually accepts), and it keeps these safe to embed in a rediss://
# URL without escaping. 64 alphanumeric characters is ample entropy.
resource "random_password" "celery_redis_auth" {
  length  = 64
  special = false
}

resource "random_password" "serverless_redis_auth" {
  length  = 64
  special = false
}

# ElastiCache Serverless does NOT accept an auth_token — it authenticates via
# RBAC user groups, so the two caches need different mechanisms.
#
# A user group must contain a user named "default"; ours is explicitly switched
# off so the only way in is the named application user.
resource "aws_elasticache_user" "default_off" {
  user_id       = "${var.project}-default-off"
  user_name     = "default"
  engine        = "redis"
  access_string = "off -@all"

  authentication_mode {
    type = "no-password-required"
  }
}

resource "aws_elasticache_user" "app" {
  user_id       = "${var.project}-app"
  user_name     = "audity_app"
  engine        = "redis"
  # Full command and key access within this cache. django_redis needs a broad
  # command set, and the cache is dedicated to this application.
  access_string = "on ~* +@all"

  authentication_mode {
    type      = "password"
    passwords = [random_password.serverless_redis_auth.result]
  }
  # Deliberately NO ignore_changes on the password. It was here initially and
  # caused a real outage of the cache: the generated password was regenerated
  # (the first attempt used punctuation ElastiCache rejects), but ignore_changes
  # stopped Terraform pushing the new value to the user, so the user kept the
  # old password while REDIS_URL carried the new one — "invalid username-password
  # pair". The password and the connection string must move together.
}

resource "aws_elasticache_user_group" "main" {
  user_group_id = "${var.project}-redis-users"
  engine        = "redis"
  user_ids      = [aws_elasticache_user.default_off.user_id, aws_elasticache_user.app.user_id]

  lifecycle {
    ignore_changes = [user_ids]
  }
}

resource "aws_elasticache_serverless_cache" "main" {
  engine             = "redis"
  name               = "${var.project}-redis"
  description        = "django_redis cache only - see cache.tf header note for why Celery is not here"
  subnet_ids         = aws_subnet.private_data[*].id
  security_group_ids = [aws_security_group.redis.id]
  user_group_id      = aws_elasticache_user_group.main.user_group_id

  cache_usage_limits {
    data_storage {
      maximum = var.redis_max_storage_gb
      unit    = "GB"
    }
    ecpu_per_second {
      maximum = var.redis_max_ecpu_per_second
    }
  }
}

# ─── Celery broker/result-backend — plain (non-cluster) node ───────────────
resource "aws_elasticache_subnet_group" "celery" {
  name       = "${var.project}-celery-redis"
  subnet_ids = aws_subnet.private_data[*].id
}

resource "aws_elasticache_replication_group" "celery" {
  replication_group_id       = "${var.project}-celery-redis"
  description                = "Celery broker/result-backend - plain Redis, not cluster-mode (Serverless above is cluster-protocol and breaks Celery kombu transport)"
  engine                     = "redis"
  engine_version             = "7.1"
  node_type                  = var.celery_redis_node_type
  num_cache_clusters         = 1 # single node — no failover/replica, matches the budget's "smallest thing that works" everywhere else
  automatic_failover_enabled = false
  multi_az_enabled           = false
  port                       = 6379
  subnet_group_name          = aws_elasticache_subnet_group.celery.name
  security_group_ids         = [aws_security_group.redis.id] # same trust boundary (ECS tasks only) as the Serverless cache
  at_rest_encryption_enabled = true                          # free, no reason not to
  transit_encryption_enabled = true                          # rediss:// — required for auth_token, and cheap insurance for task payloads
  auth_token                 = random_password.celery_redis_auth.result
  auth_token_update_strategy = "ROTATE" # ROTATE, not SET: SET requires an existing token, and this group had none
}
