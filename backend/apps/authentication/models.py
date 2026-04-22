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
