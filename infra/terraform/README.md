# Audity AWS migration — Terraform (Phases 1-3 only)

Scope: VPC/IAM/ECR/S3/CloudFront/Secrets Manager (Phase 1) → Aurora Serverless v2
+ ElastiCache Serverless (Phase 2) → ECS Fargate/ALB/WAF (Phase 3). Does **not**
touch data migration, DNS cutover, or Railway decommissioning — those need an
explicit human go-ahead each, per the operating mandate.

## One-time environment setup (per machine)

```bash
export AWS_CA_BUNDLE="$HOME/.aws/ca-bundle.pem"   # Avast TLS interception workaround for the aws CLI only
export PATH="$PATH:/c/Program Files/Amazon/AWSCLIV2"
export PATH="$PATH:/c/Users/hp/AppData/Local/Microsoft/WinGet/Packages/Hashicorp.Terraform_Microsoft.Winget.Source_8wekyb3d8bbwe"
```

## Bootstrap: state bucket (run once)

```bash
cd bootstrap
terraform init
terraform apply -var state_bucket_name=audity-terraform-state-222907083438
cd ..
```

## Init the main config against that bucket

```bash
terraform init \
  -backend-config="bucket=audity-terraform-state-222907083438" \
  -backend-config="key=audity/terraform.tfstate" \
  -backend-config="region=eu-west-1" \
  -backend-config="profile=audity-migration"
```

## Build & push the image (before the first `apply` that creates ECS services)

The ECR repo is `IMMUTABLE` — each deploy needs a new tag. `var.image_tag`
defaults to `bootstrap-v1` for this session's initial bring-up:

```bash
aws ecr get-login-password --region eu-west-1 --profile audity-migration \
  | docker login --username AWS --password-stdin <account_id>.dkr.ecr.eu-west-1.amazonaws.com

docker build -t audity-backend:bootstrap-v1 -f ../../Dockerfile ../..
docker tag audity-backend:bootstrap-v1 <account_id>.dkr.ecr.eu-west-1.amazonaws.com/audity-backend:bootstrap-v1
docker push <account_id>.dkr.ecr.eu-west-1.amazonaws.com/audity-backend:bootstrap-v1
```

## Bootstrap runbook: creating the `audity_app` RLS role

`manage.py setup_rls_role` runs SQL against the live database — Terraform has
no clean way to do that without either exposing Aurora publicly or embedding
`psql` in a provisioner. Aurora stays fully private; instead, run the command
inside the already-running `api` task via ECS Exec (no inbound access opened
at any point):

```bash
# find a running api task ID
aws ecs list-tasks --cluster audity-cluster --service-name audity-api --profile audity-migration --region eu-west-1

aws ecs execute-command \
  --cluster audity-cluster \
  --task <task-id> \
  --container api \
  --interactive \
  --command "python manage.py setup_rls_role" \
  --profile audity-migration --region eu-west-1
```

Copy the generated password from the command's output, then re-apply with
`app_database_url` set — this both creates the Secrets Manager version AND
adds it to the running ECS task definitions in one step (same mechanism as
any other TODO secret in variables.tf, see secrets.tf):

```bash
terraform apply -var app_database_url="postgresql://audity_app:<password>@<aurora-endpoint>:5432/finventory?sslmode=require"
```

This updates the `api` and `worker` task definitions and triggers a new
deployment automatically. Don't put this value in a committed `.tfvars`
file — pass it inline as above, or via a gitignored `secrets.auto.tfvars`.

## Adding real third-party secrets later

Don't put real values in `.tfvars` (risk of accidental commit). Update
Secrets Manager directly instead:

```bash
aws secretsmanager put-secret-value --secret-id audity/brevo_api_key --secret-string "<real-key>" --profile audity-migration --region eu-west-1
aws ecs update-service --cluster audity-cluster --service audity-api --force-new-deployment --profile audity-migration --region eu-west-1
```

## Cost math (see final report for the full breakdown)

Floor estimate ≈ $210/mo against the $500/mo budget, with headroom for
autoscaling bursts. NAT Gateway (~$33/mo) is the one fixed cost here that
cannot scale to zero. Single-AZ Aurora saves ~$50/mo vs Multi-AZ — see
`database.tf`'s header comment for the full trade-off.
