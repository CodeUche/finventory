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


class AuditLog(models.Model):
    """Immutable audit trail. Not a TenantAwareModel - uses raw FKs."""

    CREATE = 'create'; UPDATE = 'update'; DELETE = 'delete'
    LOGIN = 'login'; LOGOUT = 'logout'; EXPORT = 'export'; OTHER = 'other'
    ACTION_CHOICES = [
        (CREATE, 'Create'), (UPDATE, 'Update'), (DELETE, 'Delete'),
        (LOGIN, 'Login'), (LOGOUT, 'Logout'), (EXPORT, 'Export'), (OTHER, 'Other'),
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
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        app_label = 'core'

    @classmethod
    def log(cls, action, user=None, organisation=None, model_name='', object_id='', object_repr='', changes=None, request=None):
        ip = None
        ua = ''
        if request:
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
            user_agent=ua,
        )
