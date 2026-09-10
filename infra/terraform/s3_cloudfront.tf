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
# ─── CloudFront: deliberately NOT provisioned ────────────────────────────────
#
# Removed rather than shipped. The distribution served unauthenticated GET/HEAD
# and its bucket policy granted the distribution read access to every object
# under the media bucket — so any object key that leaked or was guessed could be
# fetched through the CloudFront domain by anyone. That would have quietly
# defeated the protection the application actually relies on: django-storages
# hands out short-lived presigned S3 URLs, and the bucket blocks all public
# access.
#
# Media is fully working without it (verified: a presigned URL fetched from
# outside AWS returns 200, an unsigned one returns 403), so a CDN is a
# performance nicety here, not a requirement. If it is wanted later, it must
# enforce signed URLs or signed cookies via a trusted key group, and sit behind
# WAF — at which point the bucket policy can be reintroduced alongside it.
#
# This also retires the pending "CloudFront blocked on AWS account
# verification" TODO: there is no longer anything waiting on that.
