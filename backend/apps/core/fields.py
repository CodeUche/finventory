"""
Custom model fields for security-sensitive data.

EncryptedCharField transparently encrypts values at rest using Fernet
symmetric encryption. The encryption key is derived from Django's
SECRET_KEY (or a dedicated FIELD_ENCRYPTION_KEY env var if set).

Usage:
    class MyModel(models.Model):
        secret = EncryptedCharField(max_length=500, blank=True)
"""

import base64
import hashlib

from django.conf import settings
from django.db import models


def _get_fernet():
    """Return a Fernet instance keyed from settings."""
    from cryptography.fernet import Fernet

    key_material = getattr(settings, "FIELD_ENCRYPTION_KEY", None) or settings.SECRET_KEY
    # Fernet requires a 32-byte URL-safe base64-encoded key
    digest = hashlib.sha256(key_material.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(digest)
    return Fernet(fernet_key)


class EncryptedCharField(models.TextField):
    """
    Stores an encrypted string in a TextField column.

    On save  → value is Fernet-encrypted and stored as a base64 token.
    On load  → token is decrypted and returned as a plain string.
    Empty string '' is stored as-is (no encryption overhead for blank fields).
    """

    def from_db_value(self, value, expression, connection):
        return self._decrypt(value)

    def to_python(self, value):
        return self._decrypt(value)

    def get_prep_value(self, value):
        return self._encrypt(value)

    # ── internal helpers ────────────────────────────────────────────────────

    @staticmethod
    def _encrypt(value: str | None) -> str | None:
        if not value:
            return value
        fernet = _get_fernet()
        return fernet.encrypt(value.encode()).decode()

    @staticmethod
    def _decrypt(value: str | None) -> str | None:
        if not value:
            return value
        try:
            fernet = _get_fernet()
            return fernet.decrypt(value.encode()).decode()
        except Exception:
            # Value may not be encrypted yet (e.g. during migration)
            return value
