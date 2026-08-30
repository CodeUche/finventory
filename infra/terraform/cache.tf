########################################################################
# ElastiCache Serverless for Redis
#
# Same "scale to near-zero when idle" reasoning as Aurora Serverless v2 —
# used for both the Celery broker/result-backend AND the django_redis cache
# (base.py's CACHES["default"]) via one REDIS_URL. A fixed cache.t4g.micro
# node runs ~24/7 regardless of load; Serverless bills actual ECPU/storage
# consumption, which is close to zero outside of request bursts.
#
# Caps (redis_max_storage_gb / redis_max_ecpu_per_second in variables.tf)
# exist purely as a cost backstop, not a functional requirement — protects
# against a runaway cache/broker leak turning into a surprise bill.
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

resource "aws_elasticache_serverless_cache" "main" {
  engine             = "redis"
  name               = "${var.project}-redis"
  description        = "Celery broker/result-backend + django_redis cache"
  subnet_ids         = aws_subnet.private_data[*].id
  security_group_ids = [aws_security_group.redis.id]

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
