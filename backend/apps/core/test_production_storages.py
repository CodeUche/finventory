"""
Production storage configuration — the backends Django actually resolves.

Why this file asserts *resolved classes* and not settings strings
----------------------------------------------------------------
production.py used to configure storage with STATICFILES_STORAGE and
DEFAULT_FILE_STORAGE. Django 4.2 deprecated both names and Django 5.1 (the
version pinned in requirements/base.txt) REMOVED them — assigning them is now
silently ignored: no warning, no error, the attribute just sits on the settings
module doing nothing. The result was two live production defects:

  1. USE_S3=True did nothing. Uploads (org logos, company stamps, account
     attachments, employee documents) kept going to local disk — which on
     Fargate/Railway is ephemeral and wiped on every redeploy. Files were
     already being lost: the media dir held 3 files while the database
     referenced 5.
  2. Whitenoise's compressed/manifest static storage was never active; Django
     fell back to plain StaticFilesStorage.

A test asserting `settings.DEFAULT_FILE_STORAGE == "...S3Boto3Storage"` would
have passed happily throughout — the string was there, Django just ignored it.
So every assertion below goes through the real resolution path instead:
`storages[alias]` and `default_storage.__class__` (what FileField.url calls).

Mechanics: production.py cannot be imported into the test process. It runs
fail-fast secret checks at import time and mutates the shared MIDDLEWARE list
from base.py in place, which would corrupt the settings of the running suite.
Each case therefore loads the real settings module in a subprocess with a
controlled environment, which is also a truer check — it exercises the same
import path gunicorn does at startup.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

# apps/core/test_production_storages.py -> backend/
BACKEND_DIR = Path(__file__).resolve().parents[2]

S3_BACKEND = "storages.backends.s3boto3.S3Boto3Storage"

# Runs inside the child process, under DJANGO_SETTINGS_MODULE=production.
# Reports the classes Django resolves, not the strings the settings declare.
#
# Identity is checked with issubclass, not by comparing dotted class paths:
# django-storages 1.14 turned storages.backends.s3boto3 into a compat shim
# (`S3Boto3Storage` *is* `storages.backends.s3.S3Storage`), so the resolved
# class path legitimately differs from the configured one. Class paths are
# still reported, for readable failure messages.
_PROBE = """
import json
from django.conf import settings
from django.core.files.storage import default_storage, storages
from django.core.files.storage.filesystem import FileSystemStorage
from django.contrib.staticfiles.storage import staticfiles_storage
from storages.backends.s3boto3 import S3Boto3Storage
from whitenoise.storage import CompressedManifestStaticFilesStorage


def path_of(obj):
    # default_storage / staticfiles_storage are LazyObjects; __class__ proxies
    # through to the wrapped instance, so this is the real backend class.
    cls = obj.__class__
    return cls.__module__ + "." + cls.__qualname__


print("---PROBE---" + json.dumps({
    "default_storage": path_of(default_storage),
    "storages_default": path_of(storages["default"]),
    "staticfiles_storage": path_of(staticfiles_storage),
    "default_is_s3": issubclass(default_storage.__class__, S3Boto3Storage),
    "storages_default_is_s3": issubclass(
        storages["default"].__class__, S3Boto3Storage
    ),
    "default_is_filesystem": issubclass(
        default_storage.__class__, FileSystemStorage
    ),
    "staticfiles_is_whitenoise": issubclass(
        staticfiles_storage.__class__, CompressedManifestStaticFilesStorage
    ),
    "storages_setting": getattr(settings, "STORAGES", None),
    "media_url": settings.MEDIA_URL,
    "aws_location": getattr(settings, "AWS_LOCATION", None),
    "aws_querystring_auth": getattr(settings, "AWS_QUERYSTRING_AUTH", None),
    "aws_bucket": getattr(settings, "AWS_STORAGE_BUCKET_NAME", None),
    "legacy_default_file_storage": hasattr(settings, "DEFAULT_FILE_STORAGE"),
    "legacy_staticfiles_storage": hasattr(settings, "STATICFILES_STORAGE"),
}))
"""


def _resolve_production_storages(**overrides):
    """Load config.settings.production in a subprocess; return what it resolved."""
    env = os.environ.copy()
    # Drop anything on the developer's machine that would steer the result.
    for key in list(env):
        if key.startswith("S3_") or key in {"USE_S3", "SENTRY_DSN", "APP_DATABASE_URL"}:
            del env[key]
    env.update(
        {
            "PYTHONPATH": str(BACKEND_DIR),
            "DJANGO_SETTINGS_MODULE": "config.settings.production",
            # Satisfies production.py's fail-fast startup guards. Test-only
            # values; nothing here reaches a network or a real bucket, because
            # S3Boto3Storage opens its connection lazily on first use.
            "SECRET_KEY": "test-only-key-for-storage-resolution-check-0123456789",
            "ADMIN_URL": "test-admin-path/",
            "DATABASE_URL": "postgres://u:p@localhost:5432/storage_probe",
            "DEBUG": "False",
        }
    )
    env.update(overrides)

    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        "production settings failed to load:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    marker = "---PROBE---"
    assert marker in result.stdout, f"probe produced no result:\n{result.stdout}"
    return json.loads(result.stdout.split(marker, 1)[1].splitlines()[0])


@pytest.fixture(scope="module")
def s3_enabled():
    return _resolve_production_storages(
        USE_S3="True",
        S3_BUCKET_NAME="audity-media-test",
        S3_REGION="eu-west-1",
    )


@pytest.fixture(scope="module")
def s3_disabled():
    return _resolve_production_storages(USE_S3="False")


class TestS3Enabled:
    """USE_S3=True must actually put uploads in S3."""

    def test_default_storage_is_s3(self, s3_enabled):
        # The assertion the old config would have failed: it resolved to
        # FileSystemStorage while DEFAULT_FILE_STORAGE said S3Boto3Storage.
        assert s3_enabled["default_is_s3"], (
            "default_storage resolved to "
            f"{s3_enabled['default_storage']}, not the S3 backend"
        )
        assert s3_enabled["storages_default_is_s3"], (
            f"storages['default'] resolved to {s3_enabled['storages_default']}, "
            "not the S3 backend"
        )

    def test_storages_setting_declares_s3(self, s3_enabled):
        assert s3_enabled["storages_setting"]["default"]["BACKEND"] == S3_BACKEND

    def test_staticfiles_still_whitenoise(self, s3_enabled):
        # Static files are served by whitenoise from the container even when
        # media lives in S3 — swapping "default" must not disturb this alias.
        assert s3_enabled["staticfiles_is_whitenoise"], (
            f"staticfiles resolved to {s3_enabled['staticfiles_storage']}, "
            "not whitenoise's manifest storage"
        )

    def test_s3_options_survive(self, s3_enabled):
        # The AWS_* block must still be read: signed URLs on, bucket applied.
        assert s3_enabled["aws_querystring_auth"] is True
        assert s3_enabled["aws_bucket"] == "audity-media-test"

    def test_no_key_prefix(self, s3_enabled):
        # Object keys are the models' upload_to paths at bucket root. An
        # AWS_LOCATION prefix would orphan every file path already in the DB.
        assert not s3_enabled["aws_location"]

    def test_media_url_points_at_bucket_root(self, s3_enabled):
        # MEDIA_URL is a fallback only (S3Boto3Storage.url() ignores it), but
        # it must not claim a "media/" prefix that no object key actually has.
        assert s3_enabled["media_url"] == (
            "https://audity-media-test.s3.eu-west-1.amazonaws.com/"
        )


class TestS3Disabled:
    """USE_S3=False keeps the local-filesystem default."""

    def test_default_storage_is_filesystem(self, s3_disabled):
        assert s3_disabled["default_is_filesystem"], (
            f"default_storage resolved to {s3_disabled['default_storage']}, "
            "not the local filesystem backend"
        )
        assert not s3_disabled["default_is_s3"]

    def test_staticfiles_is_whitenoise(self, s3_disabled):
        # Whitenoise applies either way — this half of the bug affected
        # Railway today, independently of the S3 migration.
        assert s3_disabled["staticfiles_is_whitenoise"], (
            f"staticfiles resolved to {s3_disabled['staticfiles_storage']}, "
            "not whitenoise's manifest storage"
        )


class TestRemovedSettingsAreNotReintroduced:
    """Guard the trap that caused this: names Django 5.1 no longer reads."""

    @pytest.mark.parametrize("case", ["s3_enabled", "s3_disabled"])
    def test_legacy_storage_settings_absent(self, case, request):
        resolved = request.getfixturevalue(case)
        assert not resolved["legacy_default_file_storage"], (
            "DEFAULT_FILE_STORAGE was removed in Django 5.1 and is silently "
            "ignored — configure STORAGES['default'] instead."
        )
        assert not resolved["legacy_staticfiles_storage"], (
            "STATICFILES_STORAGE was removed in Django 5.1 and is silently "
            "ignored — configure STORAGES['staticfiles'] instead."
        )
