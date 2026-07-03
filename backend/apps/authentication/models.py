"""
Custom User model.

Extends AbstractBaseUser + PermissionsMixin for full control.
Uses email as the primary login identifier (not username).

Security decisions:
    - Email is normalised to lowercase before storage.
    - Passwords are hashed by Django's default PBKDF2-SHA256.
    - Failed login tracking (future: account lockout after N failures).
    - `is_verified` gate prevents unverified accounts from accessing data.
"""

import secrets
import uuid

from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models

from apps.core.fields import EncryptedCharField


class UserManager(BaseUserManager):
    """Custom manager: email-first user creation."""

    def create_user(self, email: str, password: str = None, **extra_fields):
        if not email:
            raise ValueError("Email address is required.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_verified", True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Platform user.

    Belongs to one or more organisations through Membership records.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=30, blank=True)
    avatar = models.ImageField(upload_to="avatars/", null=True, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_verified = models.BooleanField(
        default=False,
        help_text="Email has been verified. Unverified users have limited access.",
    )
    is_sub_account = models.BooleanField(
        default=False,
        help_text="True for accounts created under a parent organisation. Cannot create orgs or manage billing.",
    )
    must_change_password = models.BooleanField(
        default=False,
        help_text="Forces a password change on next login. Set True for new sub-accounts.",
    )

    # MFA (TOTP)
    mfa_enabled = models.BooleanField(default=False)
    mfa_secret = EncryptedCharField(max_length=500, blank=True, default='')
    mfa_secret_pending = EncryptedCharField(max_length=500, blank=True, default='')
    mfa_backup_codes = models.JSONField(default=list, blank=True)

    # Incremented on password change to invalidate all existing JWTs
    token_version = models.PositiveIntegerField(default=0)

    # Security: track login activity
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    failed_login_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        indexes = [models.Index(fields=["email", "is_active"])]

    def __str__(self):
        return self.email

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def get_short_name(self):
        return self.first_name

    @property
    def is_locked(self) -> bool:
        from django.utils import timezone
        return self.locked_until is not None and self.locked_until > timezone.now()


class PasswordResetOTP(models.Model):
    """
    One-time password for password resets.
    Expires after 15 minutes, single-use.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "authentication.User",
        on_delete=models.CASCADE,
        related_name="password_reset_otps",
    )
    # Store only the last 6 chars for display; full code stored hashed
    code_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    used = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    @classmethod
    def generate(cls, user):
        """Invalidate previous OTPs and create a new one. Returns plain code."""
        import hashlib
        cls.objects.filter(user=user, used=False).update(used=True)
        code = str(secrets.randbelow(900000) + 100000)
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        cls.objects.create(user=user, code_hash=code_hash)
        return code

    def verify(self, code: str) -> bool:
        import hashlib
        import hmac
        from django.utils import timezone
        from datetime import timedelta
        if self.used:
            return False
        if timezone.now() > self.created_at + timedelta(minutes=15):
            return False
        candidate = hashlib.sha256(code.encode()).hexdigest()
        if hmac.compare_digest(candidate, self.code_hash):
            # Mark as used immediately to prevent replay attacks
            self.used = True
            self.save(update_fields=["used"])
            return True
        return False


class OfflineVerifier(models.Model):
    """
    Server-issued credential verifier for offline desktop re-authentication.

    Problem: the Tauri desktop app clears auth state on every launch, so a
    user who restarts the app while offline is locked out even though all
    their data is cached locally (IndexedDB + mutation queue).  The fix:
    after a successful ONLINE login the client requests a verifier — a
    PBKDF2-SHA256 hash of the password with a fresh server-generated salt —
    stores it encrypted on-device, and checks typed passwords against it to
    grant a limited "offline grace session" (enforced client-side).

    Security decisions:
        - The derived hash is returned to the client ONCE and NEVER stored
          server-side.  A DB breach therefore does not yield a second
          crackable copy of the password (the primary Argon2 hash in
          authentication_user remains the only server-side secret).
        - PBKDF2-SHA256 (not Argon2) because the client must re-derive the
          hash offline: WebCrypto's SubtleCrypto supports PBKDF2 natively in
          the Tauri webview, while Argon2 would require shipping WASM.
          600,000 iterations follows the OWASP recommendation for
          PBKDF2-HMAC-SHA256.
        - The salt is generated server-side per issuance (secrets.token_bytes)
          and is unrelated to the salt inside the user's primary password
          hash — the verifier cannot be correlated with the user table.
        - `token_version_at_issue` snapshots User.token_version.  Both the
          password-change and password-reset flows increment token_version,
          so a verifier issued before a password change is detectable as
          stale by comparing versions — even if the explicit revoke hook
          were ever skipped, staleness is still caught.
        - 14-day expiry bounds how long a stolen (encrypted) verifier blob
          stays useful; the client must re-issue on a fresh online login.
    """

    ALGORITHM = "pbkdf2_sha256"
    ITERATIONS = 600_000       # OWASP recommendation for PBKDF2-HMAC-SHA256
    SALT_BYTES = 16
    VALIDITY_DAYS = 14

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        "authentication.User",
        on_delete=models.CASCADE,
        related_name="offline_verifier",
    )
    device_label = models.CharField(
        max_length=100, blank=True, default="",
        help_text="Optional client-supplied device name for security auditing.",
    )
    token_version_at_issue = models.PositiveIntegerField(
        default=0,
        help_text="User.token_version at issuance; a mismatch means the password changed since.",
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked = models.BooleanField(default=False)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Offline verifier"
        verbose_name_plural = "Offline verifiers"

    def __str__(self):
        return f"OfflineVerifier<{self.user_id}>"

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    @classmethod
    def issue(cls, user, raw_password: str, device_label: str = ""):
        """
        Derive a fresh verifier for `user` and persist the metadata record.

        Returns (record, secret_payload) where secret_payload carries the
        base64 salt + derived hash.  The caller must hand the payload to the
        client immediately — it cannot be reconstructed later because the
        hash is intentionally not persisted.
        """
        import base64
        import hashlib
        from datetime import timedelta

        from django.utils import timezone

        salt = secrets.token_bytes(cls.SALT_BYTES)
        derived = hashlib.pbkdf2_hmac(
            "sha256", raw_password.encode("utf-8"), salt, cls.ITERATIONS
        )

        # One verifier per user: re-issuing rotates (deletes) any prior record
        # so a stale row can never resurrect an old expiry window.
        cls.objects.filter(user=user).delete()
        record = cls.objects.create(
            user=user,
            device_label=(device_label or "")[:100],
            token_version_at_issue=user.token_version or 0,
            expires_at=timezone.now() + timedelta(days=cls.VALIDITY_DAYS),
        )
        secret_payload = {
            "algorithm": cls.ALGORITHM,
            "iterations": cls.ITERATIONS,
            "salt": base64.b64encode(salt).decode(),
            "hash": base64.b64encode(derived).decode(),
        }
        return record, secret_payload

    @classmethod
    def revoke_for_user(cls, user) -> int:
        """Mark the user's verifier revoked (idempotent). Returns rows updated."""
        from django.utils import timezone
        return cls.objects.filter(user=user, revoked=False).update(
            revoked=True, revoked_at=timezone.now()
        )

    # ── State inspection ──────────────────────────────────────────────────────

    @property
    def is_expired(self) -> bool:
        from django.utils import timezone
        return timezone.now() >= self.expires_at

    @property
    def is_stale(self) -> bool:
        """True when the password changed after issuance (token_version bumped)."""
        return (self.user.token_version or 0) != self.token_version_at_issue

    @property
    def is_active(self) -> bool:
        return not self.revoked and not self.is_stale and not self.is_expired

    def inactive_reason(self):
        """Machine-readable reason for the status endpoint, or None when active."""
        if self.revoked:
            return "revoked"
        if self.is_stale:
            return "password_changed"
        if self.is_expired:
            return "expired"
        return None
