########################################################################
# VPC — public subnets (ALB, NAT) + two tiers of private subnets
# (app/ECS, data/Aurora+ElastiCache), across 2 AZs.
#
# Cost-conscious choices:
#   - ONE NAT Gateway (not one per AZ) — the plan's single biggest lever
#     against the "NAT gateway sprawl" trap. Both AZs' private subnets
#     route through it. Trade-off: if the NAT's AZ fails, private-subnet
#     egress fails until AWS recovers it — acceptable at this stage,
#     revisit with a second NAT once traffic justifies the ~$35/mo.
#   - VPC interface endpoints for ECR (api+dkr), Secrets Manager, and
#     CloudWatch Logs are deployed in ONE AZ only (not both) — halves
#     their cost (~$32/mo instead of ~$64/mo) at the cost of a small
#     amount of cross-AZ data transfer ($0.01/GB) if a task in the other
#     AZ uses them. S3 gets a gateway endpoint (free, no per-AZ cost) in
#     both route tables.
########################################################################

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${var.project}-vpc" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.project}-igw" }
}

# ─── Public subnets (ALB + NAT Gateway) ─────────────────────────────────────
resource "aws_subnet" "public" {
  count                   = length(var.azs)
  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidrs[count.index]
  availability_zone       = var.azs[count.index]
  map_public_ip_on_launch = true
  tags                    = { Name = "${var.project}-public-${var.azs[count.index]}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  tags = { Name = "${var.project}-public-rt" }
}

resource "aws_route_table_association" "public" {
  count          = length(var.azs)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# ─── Private app subnets (ECS tasks) ────────────────────────────────────────
resource "aws_subnet" "private_app" {
  count             = length(var.azs)
  vpc_id            = aws_vpc.main.id
  cidr_block        = var.private_app_subnet_cidrs[count.index]
  availability_zone = var.azs[count.index]
  tags              = { Name = "${var.project}-private-app-${var.azs[count.index]}" }
}

# ─── Private data subnets (Aurora, ElastiCache) ─────────────────────────────
resource "aws_subnet" "private_data" {
  count             = length(var.azs)
  vpc_id            = aws_vpc.main.id
  cidr_block        = var.private_data_subnet_cidrs[count.index]
  availability_zone = var.azs[count.index]
  tags              = { Name = "${var.project}-private-data-${var.azs[count.index]}" }
}

# ─── Single NAT Gateway (in AZ #1's public subnet) ──────────────────────────
resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = { Name = "${var.project}-nat-eip" }
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id
  tags          = { Name = "${var.project}-nat" }
  depends_on    = [aws_internet_gateway.main]
}

# One private route table, shared by every private subnet in both AZs —
# all default-route egress goes through the single NAT above.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }
  tags = { Name = "${var.project}-private-rt" }
}

resource "aws_route_table_association" "private_app" {
  count          = length(var.azs)
  subnet_id      = aws_subnet.private_app[count.index].id
  route_table_id = aws_route_table.private.id
}

resource "aws_route_table_association" "private_data" {
  count          = length(var.azs)
  subnet_id      = aws_subnet.private_data[count.index].id
  route_table_id = aws_route_table.private.id
}

# ─── VPC Endpoints ───────────────────────────────────────────────────────────

# S3 gateway endpoint — free, attach to the private route table so both
# app and data subnets get direct (non-NAT) S3 access.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
  tags              = { Name = "${var.project}-vpce-s3" }
}

resource "aws_security_group" "vpc_endpoints" {
  name        = "${var.project}-vpce-sg"
  description = "Allow HTTPS from within the VPC to interface endpoints"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTPS from VPC CIDR"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-vpce-sg" }
}

# Interface endpoints, deployed in ONE AZ only (private_app[0]) to halve cost
# (~$32/mo vs ~$64/mo for both AZs). ECS tasks in the other AZ still resolve
# these via the endpoint's private hosted zone at a small cross-AZ data cost.
locals {
  interface_endpoints = {
    ecr_api = "com.amazonaws.${var.aws_region}.ecr.api"
    ecr_dkr = "com.amazonaws.${var.aws_region}.ecr.dkr"
    secrets = "com.amazonaws.${var.aws_region}.secretsmanager"
    logs    = "com.amazonaws.${var.aws_region}.logs"
  }
}

resource "aws_vpc_endpoint" "interface" {
  for_each            = local.interface_endpoints
  vpc_id              = aws_vpc.main.id
  service_name        = each.value
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private_app[0].id]
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true
  tags                = { Name = "${var.project}-vpce-${each.key}" }
}
