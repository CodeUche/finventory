########################################################################
# ALB + WAF
#
# HTTP-only listener for now (port 80) — deliberately no ACM cert / HTTPS
# listener / Route 53 record yet. Those belong to Phase 8 (DNS cutover),
# which this session does not touch. The smoke-test path for this phase
# is `curl http://<alb-dns-name>/api/v1/health/` directly against the
# ALB's own amazonaws.com domain.
########################################################################

resource "aws_security_group" "alb" {
  name        = "${var.project}-alb-sg"
  description = "Public HTTP ingress to the ALB"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP from anywhere (smoke-test / pre-cutover)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # HTTPS for api.auditytechnologies.com. Without this the 443 listener
  # exists but is unreachable — the security group would silently drop
  # every TLS connection.
  ingress {
    description = "HTTPS from anywhere"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-alb-sg" }
}

resource "aws_lb" "main" {
  name               = "${var.project}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  # No deletion_protection — this is still a pre-cutover stack; leaving
  # protection off keeps teardown simple if this needs to be scrapped and
  # rebuilt during the AWS learning-curve phase.
  enable_deletion_protection = false
}

resource "aws_lb_target_group" "api" {
  name        = "${var.project}-api-tg"
  port        = var.container_port
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip" # required for awsvpc-mode Fargate tasks

  health_check {
    path                = "/api/v1/health/"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 15
    matcher             = "200"
  }

  deregistration_delay = 30 # faster rollout during this validation phase; revisit (default 300s) once real traffic exists
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

# ─── WAF ──────────────────────────────────────────────────────────────────
# Two AWS managed rule groups (common exploits + known bad inputs) plus a
# basic rate limit. Kept to a small rule count — each managed rule group is
# ~$1/mo and WAF bills per rule group evaluated, so this stays deliberately
# minimal rather than stacking every available managed group.
resource "aws_wafv2_web_acl" "main" {
  name        = "${var.project}-alb-waf"
  description = "Baseline protection for the Audity ALB"
  scope       = "REGIONAL"

  default_action {
    allow {}
  }

  rule {
    name     = "AWSManagedRulesCommonRuleSet"
    priority = 1
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project}-common-rules"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "AWSManagedRulesKnownBadInputsRuleSet"
    priority = 2
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project}-known-bad-inputs"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "RateLimitPerIP"
    priority = 3
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit              = 2000 # requests per 5-minute window per IP
        aggregate_key_type = "IP"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project}-rate-limit"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.project}-waf"
    sampled_requests_enabled   = true
  }
}

resource "aws_wafv2_web_acl_association" "main" {
  resource_arn = aws_lb.main.arn
  web_acl_arn  = aws_wafv2_web_acl.main.arn
}
