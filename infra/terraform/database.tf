########################################################################
# Aurora Serverless v2 (PostgreSQL-compatible)
#
# Deliberate deviation from the plan's literal "RDS Multi-AZ" wording —
# approved by the operating mandate: Serverless v2 scales compute down to
# 0.5 ACU when idle instead of paying for a fixed instance 24/7. Postgres
# wire-compatible, so RLS (Row Level Security) is completely unaffected —
# nothing in apps/core/rls_policy.py or the RLS migrations needs to change.
#
# single-AZ vs Multi-AZ: aurora_multi_az defaults to FALSE (see variables.tf
# for the toggle). Multi-AZ here means adding a second Aurora instance
# (a reader) in the other AZ for automatic failover — but on Serverless v2,
# that reader ALSO bills ACU-hours around the clock, roughly DOUBLING the
# Aurora line item (~$51/mo -> ~$102/mo at floor, using eu-west-1's approx
# $0.14/ACU-hr). At current pre-revenue traffic that doubling is a bigger
# lever on the $500 ceiling than the downtime risk it buys back, so this
# stays single-AZ for now — flagged explicitly in the final report for the
# user to weigh in on, not decided silently.
#
# Two-tier DB access is preserved exactly as backend/config/settings/
# production.py expects:
#   - DATABASE_URL  -> this cluster's master user (superuser, DDL-capable,
#     used only by migrate.py during the release step).
#   - APP_DATABASE_URL -> the restricted `audity_app` role, created via
#     `python manage.py setup_rls_role` (NOT by Terraform — that command
#     runs SQL against the live database, which Terraform has no clean way
#     to do without either exposing Aurora publicly or embedding psql in a
#     provisioner; ECS Exec into the running api task is the documented,
#     no-public-exposure way to run it once — see README "Bootstrap
#     runbook").
########################################################################

resource "random_password" "db_master" {
  length  = 32
  special = false # avoid characters that need extra escaping in connection-string URLs
}

resource "aws_db_subnet_group" "aurora" {
  name       = "${var.project}-aurora"
  subnet_ids = aws_subnet.private_data[*].id
  tags       = { Name = "${var.project}-aurora-subnet-group" }
}

resource "aws_security_group" "aurora" {
  name        = "${var.project}-aurora-sg"
  description = "Allow Postgres only from the ECS task security group"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Postgres from ECS tasks"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-aurora-sg" }
}

resource "aws_rds_cluster" "main" {
  cluster_identifier     = "${var.project}-aurora"
  engine                 = "aurora-postgresql"
  engine_mode            = "provisioned" # required for Serverless v2 (uses serverlessv2_scaling_configuration below)
  engine_version         = var.aurora_engine_version
  database_name          = var.db_name
  master_username        = var.db_master_username
  master_password        = random_password.db_master.result
  db_subnet_group_name   = aws_db_subnet_group.aurora.name
  vpc_security_group_ids = [aws_security_group.aurora.id]

  storage_encrypted = true

  # RDS-automated backups — this is the actual, tested backup mechanism for
  # this database (superseding the old `db-backup-cron` pg_dump service
  # referenced in the Dockerfile comment, which should be retired once this
  # cluster is the system of record — Phase 10 in the plan, not yet done).
  backup_retention_period = 7
  preferred_backup_window = "02:00-03:00" # low-traffic window, Africa/Lagos ~03:00-04:00

  # IMPORTANT: automated backups are necessary but not sufficient — per
  # standing convention, a backup is only trusted after a real pg_restore
  # has been rehearsed against it. That restore drill has NOT been run yet
  # as part of this session (it needs a completed data migration to have
  # something meaningful to restore) — flagged as an explicit TODO before
  # this counts as a tested backup, not just an assumed one.
  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.project}-aurora-final"

  serverlessv2_scaling_configuration {
    min_capacity = var.aurora_min_acu
    max_capacity = var.aurora_max_acu
  }

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [master_password] # don't fight a manual rotation
  }
}

resource "aws_rds_cluster_instance" "writer" {
  cluster_identifier  = aws_rds_cluster.main.id
  instance_class      = "db.serverless"
  engine              = aws_rds_cluster.main.engine
  engine_version      = aws_rds_cluster.main.engine_version
  publicly_accessible = false
  tags                = { Name = "${var.project}-aurora-writer" }
}

# Second (reader) instance only when aurora_multi_az = true. Off by default
# — see the header note on cost.
resource "aws_rds_cluster_instance" "reader" {
  count               = var.aurora_multi_az ? 1 : 0
  cluster_identifier  = aws_rds_cluster.main.id
  instance_class      = "db.serverless"
  engine              = aws_rds_cluster.main.engine
  engine_version      = aws_rds_cluster.main.engine_version
  publicly_accessible = false
  tags                = { Name = "${var.project}-aurora-reader" }
}
