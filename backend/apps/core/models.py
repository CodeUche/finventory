"""
Core abstract base models used across all apps.

Design decisions:
    - UUIDs as primary keys prevent enumeration attacks (IDOR mitigation).
    - Soft-delete pattern: records are never physically removed, enabling
      audit trails and accidental-deletion recovery.
    - created_by / updated_by provide full accountability.
    - All tenant-aware models inherit TenantAwareModel which enforces
      row-level isolation at the model layer.
"""

import uuid

from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base with audit timestamps."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]


class SoftDeleteManager(models.Manager):
    """Default manager that excludes soft-deleted records."""

    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class AllObjectsManager(models.Manager):
    """Manager that includes soft-deleted records (for admin/audits)."""

    def get_queryset(self):
        return super().get_queryset()


class SoftDeleteModel(TimeStampedModel):
    """
    Abstract model with soft-delete support.

    Calling .delete() marks the record as deleted rather than removing it.
    Use .hard_delete() for physical removal when absolutely necessary.
    """

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    # Two managers: default hides deleted; all_objects exposes everything
    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False):
        """Soft delete: mark record as deleted."""
        from django.utils import timezone

        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])

    def hard_delete(self):
        """Physical database deletion. Use only when legally required."""
        super().delete()

    def restore(self):
        """Undo a soft delete."""
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])


class TenantAwareModel(SoftDeleteModel):
    """
    Abstract model that enforces tenant isolation.

    Every subclass carries an organisation FK.
    The TenantMiddleware injects request.organisation so views
    never need to pass tenant IDs explicitly.

    Security: Never omit organisation filter in queries.
    The TenantQuerySet enforces this at the ORM level.
    """

    organisation = models.ForeignKey(
        "tenancy.Organisation",
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s_set",
        db_index=True,
    )

    class Meta:
        abstract = True


class MoneyField(models.DecimalField):
    """
    Convenience field for monetary values.

    Uses DECIMAL(15,4) which handles values up to ~1 trillion with 4dp.
    Never use FloatField for money - floating-point errors compound.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_digits", 15)
        kwargs.setdefault("decimal_places", 4)
        kwargs.setdefault("default", 0)
        super().__init__(*args, **kwargs)


class IdempotencyRecord(models.Model):
    """
    Stores the result of a financial write operation keyed by user + Idempotency-Key header.

    When a client sends the same Idempotency-Key on a retry, the server returns
    the cached response body and status code rather than re-processing the request.
    Records expire after 24 hours and are cleaned up by the clean_idempotency_records
    management command or a periodic Celery task.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.UUIDField(db_index=True)
    key = models.CharField(max_length=256)
    response_body = models.TextField()
    response_status = models.PositiveSmallIntegerField()
    expires_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('user_id', 'key')]
        app_label = 'core'

    def __str__(self):
        return f"IdempotencyRecord(user={self.user_id}, key={self.key[:20]}…)"


class AuditLog(models.Model):
    """Immutable audit trail. Not a TenantAwareModel - uses raw FKs."""

    CREATE = 'create'; UPDATE = 'update'; DELETE = 'delete'
    LOGIN = 'login'; LOGOUT = 'logout'; EXPORT = 'export'; OTHER = 'other'
    SUPPORT_ACCESS = 'support_access'
    ACTION_CHOICES = [
        (CREATE, 'Create'), (UPDATE, 'Update'), (DELETE, 'Delete'),
        (LOGIN, 'Login'), (LOGOUT, 'Logout'), (EXPORT, 'Export'), (OTHER, 'Other'),
        (SUPPORT_ACCESS, 'Support Access'),
    ]

    organisation_id = models.UUIDField(null=True, blank=True, db_index=True)
    user_id = models.UUIDField(null=True, blank=True, db_index=True)
    user_email = models.EmailField(blank=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    model_name = models.CharField(max_length=100, db_index=True)
    object_id = models.CharField(max_length=100, blank=True)
    object_repr = models.CharField(max_length=500, blank=True)
    changes = models.JSONField(default=dict)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    is_owner_action = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        app_label = 'core'

    @property
    def actor_label(self):
        """Human-readable actor string, suffixed with '(Owner)' for owner/superuser actions."""
        if self.is_owner_action and self.user_email:
            return f"{self.user_email} (Owner)"
        return self.user_email

    @classmethod
    def log(cls, action, user=None, organisation=None, model_name='', object_id='', object_repr='', changes=None, request=None, ip_address=None, user_agent=None, is_owner_action=False):
        ip = ip_address
        ua = user_agent
        if request is not None:
            # Mark the request so AuditTrailMiddleware doesn't double-log an
            # action that a view has already recorded with richer detail.
            try: setattr(request, '_audit_logged', True)
            except Exception: pass
        if request and ip is None and ua is None:
            try:
                from apps.core.utils import get_client_ip
                ip = get_client_ip(request) or None
            except Exception:
                ip = request.META.get('REMOTE_ADDR')
            ua = request.META.get('HTTP_USER_AGENT', '')
        cls.objects.create(
            organisation_id=organisation.id if organisation else None,
            user_id=user.id if user else None,
            user_email=user.email if user else '',
            action=action,
            model_name=model_name,
            object_id=str(object_id),
            object_repr=str(object_repr),
            changes=changes or {},
            ip_address=ip,
            user_agent=ua or '',
            is_owner_action=bool(is_owner_action) or (bool(getattr(user, 'is_superuser', False)) if user else False),
        )
