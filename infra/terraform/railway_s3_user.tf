########################################################################
# S3 credentials for Railway
#
# Railway cannot assume an IAM role the way Fargate can, so it needs a
# long-lived access key. That is a real trade-off, taken deliberately:
# Railway currently writes uploads to a container filesystem with no
# persistent volume, so every deploy destroys them. The database still
# references 9 files that no longer exist anywhere. Pointing Railway at
# the same bucket AWS uses stops that loss immediately instead of at
# cutover, and means anything uploaded before the switch is already in
# place afterwards.
#
# Scope is deliberately tight: object read/write on this one bucket and
# nothing else. No console access, no other service, no bucket-level
# administration. Delete this user once Railway is decommissioned —
# it exists only for the transition.
########################################################################

resource "aws_iam_user" "railway_media" {
  name = "${var.project}-railway-media"
  tags = {
    Purpose   = "Railway S3 media access during AWS migration"
    Temporary = "delete when Railway is decommissioned"
  }
}

resource "aws_iam_user_policy" "railway_media" {
  name = "${var.project}-railway-media"
  user = aws_iam_user.railway_media.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.media.arn}/*"
      },
      {
        # ListBucket is bucket-level, not object-level, hence the separate
        # statement. django-storages uses it to test for existence.
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.media.arn
      },
    ]
  })
}

resource "aws_iam_access_key" "railway_media" {
  user = aws_iam_user.railway_media.name
}

output "railway_s3_access_key_id" {
  value     = aws_iam_access_key.railway_media.id
  sensitive = true
}

output "railway_s3_secret_access_key" {
  value     = aws_iam_access_key.railway_media.secret
  sensitive = true
}
