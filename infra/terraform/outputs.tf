output "alb_dns_name" {
  description = "Smoke-test with: curl http://<this>/api/v1/health/"
  value       = aws_lb.main.dns_name
}

output "ecr_repository_url" {
  value = aws_ecr_repository.backend.repository_url
}

output "aurora_cluster_endpoint" {
  value = aws_rds_cluster.main.endpoint
}

output "aurora_reader_endpoint" {
  value = aws_rds_cluster.main.reader_endpoint
}

output "redis_endpoint" {
  value = aws_elasticache_serverless_cache.main.endpoint[0].address
}

output "media_bucket_name" {
  value = aws_s3_bucket.media.id
}

output "cloudfront_domain_name" {
  value = aws_cloudfront_distribution.media.domain_name
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "migrate_task_definition_arn" {
  description = "Run this as a one-off task before every deploy — see README 'Deploy runbook'. Never let api/worker/beat run migrations themselves."
  value       = aws_ecs_task_definition.migrate.arn
}

output "private_app_subnet_ids" {
  description = "For the --network-configuration flag on `aws ecs run-task` (migrate task runbook)."
  value       = aws_subnet.private_app[*].id
}

output "ecs_tasks_security_group_id" {
  description = "For the --network-configuration flag on `aws ecs run-task` (migrate task runbook)."
  value       = aws_security_group.ecs_tasks.id
}

output "admin_url_generated" {
  description = "Random obfuscated Django admin path — matches production.py's fail-fast guard."
  value       = local.admin_url
  sensitive   = true
}
