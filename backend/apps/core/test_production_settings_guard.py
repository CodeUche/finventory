"""
M-9 — production must refuse to start without FIELD_ENCRYPTION_KEY.

apps/core/fields.py falls back to deriving the encryption key from SECRET_KEY
when FIELD_ENCRYPTION_KEY is unset. That fallback is fine for local development,
where nothing sensitive is stored, but a fintech product's MFA secrets, SMTP
passwords and e-invoicing API keys deserve a key with one job — not one shared
with session/JWT signing and CSRF, where rotating it for that unrelated reason
would also silently corrupt every encrypted value.

This was worse than "unset" for three months: FIELD_ENCRYPTION_KEY was never
wired into any Django settings file at all. Setting the environment variable
did nothing — ``getattr(settings, "FIELD_ENCRYPTION_KEY", None)`` always
returned ``None`` regardless, because the attribute never existed on the
settings object. That gap is closed in ``config/settings/base.py``.

This test cannot import ``config.settings.production`` directly in-process —
Django settings are configured once per interpreter and the checks below run
at *module import time*, which is the whole point (fail at startup, not on the
first request). So it spawns a real subprocess, exactly reproducing how the
server actually boots, and inspects the exit code.

    pytest apps/core/test_production_settings_guard.py

Requires no database and no live services — production.py's other checks
(Sentry, S3) are both no-ops when their env vars are absent, so this only
needs the handful of variables the fail-fast block itself demands.
"""

import os
import subprocess
import sys

import pytest

_BASE_ENV = {
    "SECRET_KEY": "x" * 50,
    "DATABASE_URL": "postgres://u:p@localhost:5432/d",
    "ADMIN_URL": "a1b2c3d4e5f6a1b2/",
    "DEBUG": "False",
}


def _try_import_production_settings(extra_env):
    """
    Spawn a subprocess that attempts ``django.setup()`` under
    config.settings.production with the given environment, isolated from
    whatever real .env / OS environment this test process has (so a
    developer's own local FIELD_ENCRYPTION_KEY, if any, cannot mask a
    regression here).
    """
    env = {"PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}
    env.update(_BASE_ENV)
    env.update(extra_env)
    env["DJANGO_SETTINGS_MODULE"] = "config.settings.production"

    result = subprocess.run(
        [sys.executable, "-c", "import django; django.setup()"],
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result


# Module-level functions, deliberately not a plain class. This project's
# pytest.ini collects classes matching python_classes = "Test*", or any class
# inheriting unittest.TestCase — nothing else. A bare class here would be
# silently skipped by pytest while still "existing" in the file, which is
# exactly the NEW-13 trap (90 payroll tests never collected for the same
# reason) this project has already been bitten by once.


@pytest.mark.slow
def test_missing_field_encryption_key_refuses_to_boot():
    result = _try_import_production_settings({})
    assert result.returncode != 0, (
        "production settings imported successfully with no "
        "FIELD_ENCRYPTION_KEY set — the fail-fast guard is not in effect"
    )
    assert "FIELD_ENCRYPTION_KEY" in result.stderr


@pytest.mark.slow
def test_a_short_field_encryption_key_also_refuses_to_boot():
    result = _try_import_production_settings({"FIELD_ENCRYPTION_KEY": "too-short"})
    assert result.returncode != 0
    assert "FIELD_ENCRYPTION_KEY" in result.stderr


@pytest.mark.slow
def test_a_placeholder_value_refuses_to_boot():
    result = _try_import_production_settings({"FIELD_ENCRYPTION_KEY": "change-me-" + "x" * 30})
    assert result.returncode != 0
    assert "placeholder" in result.stderr


@pytest.mark.slow
def test_a_real_key_boots_cleanly():
    """
    The positive control. Without it, the three tests above could pass for
    the wrong reason — production.py failing to import at all, for some
    unrelated cause, on every input including a good one.
    """
    result = _try_import_production_settings({"FIELD_ENCRYPTION_KEY": "y" * 48})
    assert result.returncode == 0, result.stderr
