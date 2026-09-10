########################################################################
# ECR — one repo, holds the same multi-stage image already built by
# `finventory/Dockerfile`. All three ECS services (api/worker/beat) pull
# the same image tag and differ only by container `command`, mirroring
# how Railway splits them today via "start commands".
########################################################################

resource "aws_ecr_repository" "backend" {
  name                 = "${var.project}-backend"
  image_tag_mutability = "IMMUTABLE" # deploys must push a new tag — no silent overwrite of :latest

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Keep storage cost bounded — only the last 15 images are retained.
# Untagged layers are safe to expire aggressively — nothing can reference them.
# Tagged images are NOT expired by count: CI pushes one tag per commit, while
# ECS deployments are manual, so a count rule can delete the very image a
# running task definition still points at. A replacement task would then fail
# to pull, and the rollback target would be gone precisely when it is needed.
# Tagged images are cheap (a few hundred MB); prune them deliberately instead.
resource "aws_ecr_lifecycle_policy" "backend" {
  repository = aws_ecr_repository.backend.name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after 7 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      },
    ]
  })
}
