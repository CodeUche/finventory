########################################################################
# S3 (media bucket) + CloudFront
#
# Activates the USE_S3 code path already built into production.py. The
# bucket stays fully private (no public ACL, no bucket policy allowing
# public reads) — django-storages continues generating short-lived signed
# S3 URLs directly (AWS_QUERYSTRING_AUTH=True, already the default),
# which is the one access pattern guaranteed to work without further
# testing.
#
# CloudFront is provisioned here (OAC-fronted, ready to use) but NOT yet
# wired into MEDIA_URL / AWS_S3_CUSTOM_DOMAIN. Routing django-storages'
# SigV4-signed URLs through a CloudFront custom domain needs verification
# that the signature still validates once the Host header changes — rather
# than guess, this is left as a documented fast-follow (see README) so
# private tenant documents (receipts, letterheads) are never at risk of a
# silent access break.
########################################################################

resource "aws_s3_bucket" "media" {
  bucket = "${var.project}-media-${var.account_id}"
}

resource "aws_s3_bucket_versioning" "media" {
  bucket = aws_s3_bucket.media.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "media" {
  bucket = aws_s3_bucket.media.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "media" {
  bucket                  = aws_s3_bucket.media.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_cors_configuration" "media" {
  bucket = aws_s3_bucket.media.id
  cors_rule {
    allowed_methods = ["GET", "HEAD"]
    allowed_origins = ["*"] # media reads are via signed URL; tightening further adds no security here
    allowed_headers = ["*"]
    max_age_seconds = 3600
  }
}

# Lifecycle: media isn't disposable, so no expiration rule — just clean up
# noncurrent (superseded) versions after 90 days to bound storage cost from
# versioning without losing recent history.
resource "aws_s3_bucket_lifecycle_configuration" "media" {
  bucket = aws_s3_bucket.media.id
  rule {
    id     = "expire-old-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

# ─── CloudFront (provisioned, not yet load-bearing — see header note) ──────
resource "aws_cloudfront_origin_access_control" "media" {
  name                              = "${var.project}-media-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "media" {
  enabled     = true
  comment     = "${var.project} media CDN"
  price_class = "PriceClass_100" # cheapest tier: North America + Europe edge locations only — matches where Audity's traffic actually is (Nigeria via European PoPs)

  origin {
    domain_name              = aws_s3_bucket.media.bucket_regional_domain_name
    origin_id                = "media-s3-origin"
    origin_access_control_id = aws_cloudfront_origin_access_control.media.id
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "media-s3-origin"
    viewer_protocol_policy = "redirect-to-https"

    forwarded_values {
      query_string = true # required so any future SigV4-through-CDN signed URLs still validate
      cookies {
        forward = "none"
      }
    }

    min_ttl     = 0
    default_ttl = 86400
    max_ttl     = 604800
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# Bucket policy: only this specific CloudFront distribution (via OAC) may
# read from the bucket — not "any CloudFront distribution in the account".
data "aws_iam_policy_document" "media_bucket_policy" {
  statement {
    sid       = "AllowCloudFrontServicePrincipalReadOnly"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.media.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.media.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "media" {
  bucket = aws_s3_bucket.media.id
  policy = data.aws_iam_policy_document.media_bucket_policy.json
}
