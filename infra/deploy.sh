#!/usr/bin/env bash
#
# Deploy a backend build to AWS.
#
# Deploys are deliberately manual. CI builds and pushes an image to ECR and
# stops there: the GitHub OIDC role has ECR rights and nothing else, so a
# compromised workflow cannot roll production (see infra/terraform/github_oidc.tf).
# This script runs on YOUR credentials instead, and is the supported way to ship.
#
# Usage:
#   ./infra/deploy.sh                 # deploy the image built from origin/main
#   ./infra/deploy.sh <git-sha>       # deploy a specific image tag
#   DRY_RUN=1 ./infra/deploy.sh       # show what would happen, change nothing
#
# What it does, in order:
#   1. Resolves the image tag and checks that image actually exists in ECR
#   2. Runs migrations ONCE as a standalone task and waits for it to succeed
#      (never per-container — see the concurrent-migrate race in ecs.tf)
#   3. Rolls the three services onto the new image via terraform apply
#   4. Waits for the rollout and checks the health endpoint
#
# Migrations gate the rollout: if step 2 fails, nothing is deployed.

set -euo pipefail

REGION="${AWS_REGION:-eu-west-1}"
CLUSTER="audity-cluster"
REPO="audity-backend"
HEALTH_URL="https://api.auditytechnologies.com/api/v1/health/"
TF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/terraform" && pwd)"
DRY_RUN="${DRY_RUN:-0}"

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# ── 1. Resolve and verify the image ──────────────────────────────────────────
TAG="${1:-}"
if [ -z "$TAG" ]; then
  TAG="$(git rev-parse origin/main)"
  say "No tag given — using origin/main: ${TAG:0:12}"
fi

say "Checking the image exists in ECR"
aws ecr describe-images --repository-name "$REPO" --image-ids "imageTag=$TAG" \
  --region "$REGION" --query 'imageDetails[0].imagePushedAt' --output text \
  || fail "No image tagged $TAG in ECR. CI pushes one per commit to main — has that build finished?"

CURRENT="$(aws ecs describe-task-definition --task-definition audity-api --region "$REGION" \
  --query 'taskDefinition.containerDefinitions[0].image' --output text | cut -d: -f2)"
say "Currently deployed: ${CURRENT:0:12}    Deploying: ${TAG:0:12}"
[ "$CURRENT" = "$TAG" ] && say "That image is already live. Continuing anyway (this re-runs migrations)."

if [ "$DRY_RUN" = "1" ]; then say "DRY_RUN=1 — stopping here, nothing changed."; exit 0; fi

# ── 2. Migrations, once, as a standalone task ────────────────────────────────
say "Running migrations as a one-off task"
SUBNETS="$(cd "$TF_DIR" && terraform output -json private_app_subnet_ids | tr -d '[]"\n ' )"
SG="$(cd "$TF_DIR" && terraform output -raw ecs_tasks_security_group_id)"

TASK_ARN="$(aws ecs run-task \
  --cluster "$CLUSTER" \
  --task-definition audity-migrate \
  --launch-type FARGATE \
  --region "$REGION" \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SG],assignPublicIp=DISABLED}" \
  --query 'tasks[0].taskArn' --output text)"
[ -n "$TASK_ARN" ] && [ "$TASK_ARN" != "None" ] || fail "Could not start the migrate task."
echo "  task: ${TASK_ARN##*/}"

echo "  waiting for migrations to finish..."
aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$TASK_ARN" --region "$REGION"

EXIT_CODE="$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK_ARN" --region "$REGION" \
  --query 'tasks[0].containers[0].exitCode' --output text)"
if [ "$EXIT_CODE" != "0" ]; then
  echo "  migrate task exited $EXIT_CODE — logs:"
  aws logs tail "/ecs/audity/migrate" --since 10m --region "$REGION" 2>/dev/null | tail -40 || true
  fail "Migrations failed. NOTHING has been deployed — the running services are untouched."
fi
say "Migrations succeeded"

# ── 3. Roll the services ─────────────────────────────────────────────────────
say "Rolling services onto ${TAG:0:12}"
FEK="$(aws secretsmanager get-secret-value --secret-id audity/field_encryption_key \
        --region "$REGION" --query SecretString --output text)"

# NOTE: on the Windows dev machine, Avast's TLS interception breaks terraform's
# plugin handshake — run terraform through Docker there. See project memory.
( cd "$TF_DIR" && TF_VAR_field_encryption_key="$FEK" TF_VAR_image_tag="$TAG" \
    terraform apply -input=false -auto-approve )

# ── 4. Verify ────────────────────────────────────────────────────────────────
say "Waiting for the rollout to settle"
aws ecs wait services-stable --cluster "$CLUSTER" \
  --services audity-api audity-worker audity-beat --region "$REGION"

say "Health check"
for i in 1 2 3 4 5; do
  STATUS="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$HEALTH_URL" || echo 000)"
  echo "  attempt $i/5: HTTP $STATUS"
  if [ "$STATUS" = "200" ]; then
    say "Deployed ${TAG:0:12} successfully"
    exit 0
  fi
  sleep 10
done

fail "Services rolled but the health endpoint is not returning 200. Check:
  aws ecs describe-services --cluster $CLUSTER --services audity-api --region $REGION
  aws logs tail /ecs/audity/api --since 10m --region $REGION"
