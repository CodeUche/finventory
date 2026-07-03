"""
OfflineVerifier — metadata record backing offline desktop re-authentication.

Deliberately stores NO secret material: the PBKDF2 salt + derived hash are
returned to the client once at issuance and never persisted, so this table
adds zero password-cracking surface in a DB breach.  Only the bookkeeping
needed for the status/revocation endpoints lives here (expiry, revoked flag,
and a token_version snapshot that detects password changes).
"""

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("authentication", "0006_security_token_version_mfa_encryption"),
    ]

    operations = [
        migrations.CreateModel(
            name="OfflineVerifier",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("device_label", models.CharField(blank=True, default="", help_text="Optional client-supplied device name for security auditing.", max_length=100)),
                ("token_version_at_issue", models.PositiveIntegerField(default=0, help_text="User.token_version at issuance; a mismatch means the password changed since.")),
                ("issued_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
                ("revoked", models.BooleanField(default=False)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="offline_verifier", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "Offline verifier",
                "verbose_name_plural": "Offline verifiers",
            },
        ),
    ]
