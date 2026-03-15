"""
Tenancy models: Organisation and Membership.

Architecture:
    - Each Organisation is a completely isolated tenant.
    - Users join organisations through Membership records with explicit roles.
    - All business data is scoped to an organisation via ForeignKey.
    - The `slug` field enables subdomain-based routing in future.

Security:
    - Membership.is_active must be checked on every request.
    - Deactivating a membership immediately revokes all access.
"""

import uuid

from django.conf import settings
from django.db import models

from apps.core.fields import EncryptedCharField
from apps.core.models import SoftDeleteModel, TimeStampedModel


class Organisation(SoftDeleteModel):
    """
    A tenant in the SaaS platform.

    Represents a business using the platform. All data is isolated per organisation.
    """

    class AccountType(models.TextChoices):
        PERSONAL = "personal", "Personal"
        BUSINESS = "business", "Business"

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=100, unique=True, db_index=True)
    account_type = models.CharField(
        max_length=20,
        choices=AccountType.choices,
        default=AccountType.BUSINESS,
    )
    # Business details
    registration_number = models.CharField(max_length=100, blank=True)
    tax_id = models.CharField(max_length=100, blank=True, help_text="VAT/TIN number")
    country = models.CharField(max_length=2, default="NG", help_text="ISO 3166-1 alpha-2")
    currency = models.CharField(max_length=3, default="NGN", help_text="ISO 4217")
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    logo = models.ImageField(upload_to="org_logos/", null=True, blank=True)
    letterhead = models.FileField(upload_to="org_letterheads/", null=True, blank=True,
        help_text="Optional letterhead file (image, PDF, or DOC) shown at the top of invoices and PDF documents")
    # Banking details (shown on invoices and payment documents)
    bank_name = models.CharField(max_length=200, blank=True)
    bank_account_number = models.CharField(max_length=30, blank=True)
    bank_account_name = models.CharField(max_length=200, blank=True)
    bank_sort_code = models.CharField(max_length=20, blank=True, help_text="Sort code or routing number")
    # Document branding preferences
    brand_color = models.CharField(
        max_length=7, default="#f97316",
        help_text="Hex color code (#rrggbb) used in invoice/PDF templates when no letterhead is uploaded"
    )
    use_letterhead = models.BooleanField(
        default=False,
        help_text="When True, use the uploaded letterhead banner instead of the colored template header"
    )
    # Subscription link (set by subscriptions app)
    subscription = models.OneToOneField(
        "subscriptions.Subscription",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="organisation",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_organisations",
    )
    is_active = models.BooleanField(default=True)

    class Meta(SoftDeleteModel.Meta):
        verbose_name = "Organisation"
        verbose_name_plural = "Organisations"

    def __str__(self):
        return self.name


class Membership(TimeStampedModel):
    """
    Junction between User and Organisation with role assignment.

    RBAC is enforced through this model.
    One user can belong to multiple organisations with different roles.
    """

    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        MANAGER = "manager", "Manager"
        ACCOUNTANT = "accountant", "Accountant"
        STAFF = "staff", "Staff"
        VIEWER = "viewer", "Viewer"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STAFF)
    is_active = models.BooleanField(default=True, db_index=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_invitations",
    )
    joined_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [["user", "organisation"]]
        verbose_name = "Membership"
        verbose_name_plural = "Memberships"
        indexes = [
            models.Index(fields=["organisation", "is_active"]),
            models.Index(fields=["user", "is_active"]),
        ]

    def __str__(self):
        return f"{self.user} @ {self.organisation} ({self.role})"


class EmailConfig(TimeStampedModel):
    """Per-organisation SMTP configuration for sending transactional emails."""

    organisation = models.OneToOneField(
        Organisation, on_delete=models.CASCADE, related_name="email_config"
    )
    smtp_host = models.CharField(max_length=255, default="smtp.gmail.com")
    smtp_port = models.PositiveSmallIntegerField(default=587)
    smtp_username = models.CharField(max_length=255, blank=True)
    smtp_password = EncryptedCharField(max_length=255, blank=True, help_text="Encrypted at rest — use app passwords")
    use_tls = models.BooleanField(default=True)
    from_name = models.CharField(max_length=255, blank=True)
    from_email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Email Config"

    def __str__(self):
        return f"EmailConfig for {self.organisation}"


class ModulePermission(TimeStampedModel):
    """
    Granular per-module access control for a Membership.

    Owners and admins always have full access regardless of these records.
    For all other roles (manager, accountant, staff, viewer), the admin can
    override each module individually:
      none  — module is hidden from the sidebar
      view  — read-only access
      write — can create new records but cannot edit/delete existing ones
      edit  — full create / edit / delete access
    """

    MODULE_CHOICES = [
        ('sales', 'Sales / Invoices'),
        ('purchases', 'Purchase Orders'),
        ('bills', 'Bills / Payables'),
        ('expenses', 'Expenses'),
        ('inventory', 'Inventory'),
        ('customers', 'Customers'),
        ('suppliers', 'Suppliers'),
        ('payroll', 'Payroll'),
        ('reports', 'Reports'),
        ('accounting', 'Accounting'),
        ('tax', 'Tax'),
        ('budget', 'Budget'),
        ('quotes', 'Quotes'),
        ('recurring', 'Recurring Invoices'),
    ]

    ACCESS_CHOICES = [
        ('none', 'No Access'),
        ('view', 'View Only'),
        ('write', 'Enter & Save'),
        ('edit', 'Full Edit'),
    ]

    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name='module_permissions'
    )
    module = models.CharField(max_length=30, choices=MODULE_CHOICES)
    access_level = models.CharField(max_length=10, choices=ACCESS_CHOICES, default='edit')

    class Meta:
        unique_together = [['membership', 'module']]
        verbose_name = 'Module Permission'

    def __str__(self):
        return f"{self.membership} — {self.module}: {self.access_level}"


class Invitation(TimeStampedModel):
    """
    Pending invitation to join an organisation.

    Token is short-lived and single-use. After acceptance it is marked consumed.
    """

    token = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="invitations"
    )
    email = models.EmailField()
    role = models.CharField(
        max_length=20, choices=Membership.Role.choices, default=Membership.Role.STAFF
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="invitations_sent",
    )
    is_consumed = models.BooleanField(default=False)
    expires_at = models.DateTimeField()

    class Meta:
        verbose_name = "Invitation"

    def __str__(self):
        return f"Invite {self.email} → {self.organisation}"
