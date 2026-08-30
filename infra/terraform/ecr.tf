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
resource "aws_ecr_lifecycle_policy" "backend" {
  repository = aws_ecr_repository.backend.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 15 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 15
      }
      action = { type = "expire" }
    }]
  })
}
