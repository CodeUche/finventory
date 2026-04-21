"""
Management command: backup_db

Dumps the PostgreSQL database and uploads it to S3-compatible storage (R2/S3).
Designed to be run as a Railway cron job daily.

Usage:
    python manage.py backup_db

Env vars required (same as production S3 settings):
    DATABASE_URL, USE_S3, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
    AWS_STORAGE_BUCKET_NAME, AWS_S3_ENDPOINT_URL (for R2)
"""

import os
import subprocess
import tempfile
from datetime import datetime, timezone

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Dump the database and upload to S3/R2 storage."

    def add_arguments(self, parser):
        parser.add_argument(
            "--retain",
            type=int,
            default=30,
            help="Number of daily backups to keep (default: 30)",
        )

    def handle(self, *args, **options):
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            self.stderr.write("DATABASE_URL is not set — aborting.")
            return

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"backup_{timestamp}.dump"

        self.stdout.write(f"Starting backup: {filename}")

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, filename)

            result = subprocess.run(
                ["pg_dump", "--format=custom", "--no-acl", "--no-owner", database_url],
                stdout=open(filepath, "wb"),
                stderr=subprocess.PIPE,
            )

            if result.returncode != 0:
                self.stderr.write(f"pg_dump failed: {result.stderr.decode()}")
                raise SystemExit(1)

            size_mb = os.path.getsize(filepath) / (1024 * 1024)
            self.stdout.write(f"Dump created: {size_mb:.2f} MB")

            self._upload(filepath, filename)

        self.stdout.write(self.style.SUCCESS(f"Backup complete: {filename}"))

    def _upload(self, filepath, filename):
        import boto3

        bucket = os.environ["AWS_STORAGE_BUCKET_NAME"]
        key = f"db-backups/{filename}"

        s3 = boto3.client(
            "s3",
            endpoint_url=os.environ.get("AWS_S3_ENDPOINT_URL"),
            aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
            region_name=os.environ.get("AWS_S3_REGION_NAME", "auto"),
        )

        self.stdout.write(f"Uploading to {bucket}/{key} ...")
        s3.upload_file(filepath, bucket, key)
        self.stdout.write("Upload complete.")
