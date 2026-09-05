########################################################################
# API custom domain + TLS
#
# Why a custom domain at all: the clients (Vercel web, Tauri desktop,
# Capacitor Android) currently hardcode Railway's own hostname
# (audity-backend-production-30f9.up.railway.app), which Railway controls
# and we cannot repoint. That makes every future infrastructure move a
# client-release event. Putting the API behind api.auditytechnologies.com
# fixes that permanently, and is required regardless because the ALB needs
# a certificate — sending credentials to a raw ALB hostname over plain
# HTTP is not acceptable for this application.
#
# DNS for auditytechnologies.com is hosted at Namecheap (pdns1/pdns2.
# registrar-servers.com), not Route 53, and the apex already points at
# Vercel (76.76.21.21) for the marketing/web app. We therefore do NOT
# delegate the zone — that would risk the website. Instead two CNAME
# records get added by hand at Namecheap:
#   1. the ACM validation record output below
#   2. api -> the ALB's DNS name
#
# Split into two applies on purpose: this file only REQUESTS the
# certificate. The aws_acm_certificate_validation + HTTPS listener come
# after the validation record exists, otherwise Terraform blocks waiting.
########################################################################

variable "api_domain_name" {
  description = "Custom domain for the API. Empty disables all custom-domain/TLS resources."
  type        = string
  default     = "api.auditytechnologies.com"
}

resource "aws_acm_certificate" "api" {
  count             = var.api_domain_name == "" ? 0 : 1
  domain_name       = var.api_domain_name
  validation_method = "DNS"

  tags = {
    Name = "${var.project}-api-cert"
  }

  lifecycle {
    create_before_destroy = true
  }
}

output "acm_validation_record" {
  description = "Add this CNAME at Namecheap to validate the certificate."
  value = var.api_domain_name == "" ? null : {
    for o in aws_acm_certificate.api[0].domain_validation_options :
    o.domain_name => {
      name  = o.resource_record_name
      type  = o.resource_record_type
      value = o.resource_record_value
    }
  }
}

output "alb_dns_name_for_cname" {
  description = "Point the api CNAME at this once the certificate is validated."
  value       = aws_lb.main.dns_name
}

########################################################################
# HTTPS listener
#
# Added only after the ACM certificate reaches ISSUED — the validation
# resource below blocks until AWS has seen the DNS record, so a premature
# apply waits rather than creating a listener with an unusable cert.
#
# The port-80 listener in alb_waf.tf is deliberately left forwarding (not
# redirecting) for now: desktop and mobile clients still have Railway's
# hostname compiled in, and until they are updated the raw ALB over HTTP
# is the only way to reach this stack for testing. Switching 80 to a
# redirect happens at cutover, together with re-enabling
# SECURE_SSL_REDIRECT — see the Phase 8 notes.
########################################################################

resource "aws_acm_certificate_validation" "api" {
  count           = var.api_domain_name == "" ? 0 : 1
  certificate_arn = aws_acm_certificate.api[0].arn
  # No validation_record_fqdns: the records live at Namecheap, not Route 53,
  # so Terraform cannot create them. It only waits for AWS to observe them.
}

resource "aws_lb_listener" "https" {
  count             = var.api_domain_name == "" ? 0 : 1
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  # Modern policy: TLS 1.2 minimum. The clients here are browsers, a Tauri
  # webview and an Android webview — none need legacy TLS.
  ssl_policy      = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn = aws_acm_certificate_validation.api[0].certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}
