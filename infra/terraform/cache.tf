########################################################################
# ONE Redis node, serving both the django_redis cache and Celery.
#
# It used to be two. ElastiCache Serverless for Redis speaks Redis Cluster
# protocol even behind its single endpoint, and Celery's kombu transport
# issues multi-key MULTI/EXEC operations on worker startup ("mingle"), which
# Cluster mode rejects: every celery-worker task crashed on boot with
# "CROSSSLOT Keys in request don't hash to the same slot". So Celery got its
# own plain non-cluster node while the cache stayed on Serverless.
#
# That split was removed on 2026-09-28 on cost grounds. Serverless bills a
# ~1 GB storage minimum regardless of use, which came to $85.82 in September,
# about a third of the whole AWS bill, for a cache CloudWatch measured at
# 0.00 MB used with $0.002 of request activity. The node below costs $9.33/mo
# and was already running.
#
# Both now live here on separate DB indexes (cache 2, broker 0, results 1),
# which a plain node supports and Cluster mode does not. Note the coupling
# this introduces: one node is now a single point of failure for the cache AND
# the task queue, where before each had its own. Neither ever had a replica,
# so this trades two single points for one rather than adding risk, but a
# replica here is the obvious next hardening step if uptime matters more than
# the ~$9/mo it would add.
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
