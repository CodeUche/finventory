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
    company_stamp = models.ImageField(
        upload_to="org_stamps/", null=True, blank=True,
        help_text="Optional digital company stamp/seal shown on invoices and delivery notes"
    )
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
    # Invoice header customisation
    invoice_company_name = models.CharField(
        max_length=255, blank=True,
        help_text="Override the company name shown on invoices/PDFs. Leave blank to use the organisation name."
    )
    company_name_font = models.CharField(
        max_length=100, default='helvetica',
        help_text="Font used for the company name on invoices and PDF documents"
    )
    company_name_font_color = models.CharField(
        max_length=7, default='#ffffff',
        help_text="Hex color for the company name text on invoices"
    )
    company_name_font_size = models.PositiveSmallIntegerField(
        default=14,
        help_text="Font size (pt) for the company name on invoices"
    )
    company_name_font_bold = models.BooleanField(
        default=True,
        help_text="Whether the company name is bold on invoices"
    )
    company_name_font_italic = models.BooleanField(
        default=False,
        help_text="Whether the company name is italic on invoices"
    )
    company_name_font_underline = models.BooleanField(
        default=False,
        help_text="Whether the company name is underlined on invoices"
    )
    show_company_name_on_pdf = models.BooleanField(
        default=True,
        help_text="Whether to show the company name text on invoices and PDFs (alongside the logo)"
    )
    # Invoice template
    invoice_template = models.CharField(
        max_length=30, default='classic',
        help_text="Invoice PDF layout template: classic, modern, minimal, professional"
    )
    # Payroll — default pension provider (PFA)
    pension_provider = models.CharField(
        max_length=100, blank=True,
        help_text="Default Pension Fund Administrator (PFA) for remittance guidance"
    )
    # AI assistant custom context (per-org training)
    ai_custom_context = models.TextField(
        blank=True,
        help_text="Custom business context that personalises the AI assistant for this organisation"
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
    parent_org = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='child_entities',
        help_text="Parent organisation for multi-entity groups (Enterprise only).",
    )
    entity_group_name = models.CharField(
        max_length=100, blank=True,
        help_text="Short label for this entity within the group (e.g. 'Lagos Branch', 'Holdings').",
    )
    is_active = models.BooleanField(default=True)
    # Set to True once the user explicitly completes the onboarding flow
    # (selects a plan and pays, or deliberately chooses the free plan).
    # Until this is True, the user is redirected to /onboarding on every login.
    onboarding_completed = models.BooleanField(default=False)

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
        ('settings', 'Settings (Company / Billing)'),
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
    is_rejected = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    module_permissions = models.JSONField(
        default=dict,
        blank=True,
        help_text='Optional per-module access overrides: {"sales": "edit", "reports": "view", ...}',
    )

    class Meta:
        verbose_name = "Invitation"

    @property
    def status(self):
        if self.is_consumed:
            return "accepted"
        if self.is_rejected:
            return "rejected"
        from django.utils import timezone
        if self.expires_at < timezone.now():
            return "expired"
        return "pending"

    def __str__(self):
        return f"Invite {self.email} → {self.organisation}"


class PartnerProfile(TimeStampedModel):
    """
    Accountant / bookkeeper partner profile.

    A user with a PartnerProfile can manage multiple SMB client organisations
    from a single dashboard. They pay a partner-tier licence fee and each SMB
    they bring on is an independent Audity subscriber.

    Tiers (controlled by plan slug on their personal subscription):
        partner-starter  — up to 10 clients
        partner-pro      — up to 30 clients
        partner-agency   — unlimited clients

    Revenue layers:
        1. Partner licence fee   — the partner subscription itself
        2. Per-client seat       — each SMB org retains its own subscription
        3. Volume tiers          — higher caps at higher tier
        4. Referral commission   — commission_rate % on referred client payments
        5. Premium tools upsell  — white_label, consolidated_reporting flags
    """

    class Tier(models.TextChoices):
        STARTER = "starter", "Partner Starter (10 clients)"
        PRO     = "pro",     "Partner Pro (30 clients)"
        AGENCY  = "agency",  "Partner Agency (Unlimited)"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="partner_profile",
    )
    tier = models.CharField(max_length=20, choices=Tier.choices, default=Tier.STARTER)
    firm_name = models.CharField(max_length=200, blank=True)
    firm_logo = models.ImageField(upload_to="partner_logos/", null=True, blank=True)
    # Max clients allowed — enforced in PartnerClientLink
    max_clients = models.PositiveIntegerField(default=10)
    # Referral commission earned (percentage)
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=5)
    total_commission_earned = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    # Unique referral code — share this link with prospective clients
    # Format: REF-XXXXXX (6 uppercase hex chars derived from user UUID)
    referral_code = models.CharField(max_length=20, unique=True, blank=True, db_index=True)
    # Premium tool flags (unlocked by higher tiers)
    white_label_reports = models.BooleanField(default=False)
    consolidated_reporting = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = "Partner Profile"

    def save(self, *args, **kwargs):
        if not self.referral_code:
            self.referral_code = f"REF-{str(self.user.id).replace('-', '').upper()[:6]}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Partner: {self.user.email} ({self.tier})"

    @property
    def active_client_count(self):
        return self.clients.filter(is_active=True).count()

    @property
    def can_add_client(self):
        if self.max_clients >= 999999:
            return True
        return self.active_client_count < self.max_clients


class PartnerClientLink(TimeStampedModel):
    """
    Links a partner to a client organisation they manage.

    The client org retains its own subscription; the partner just gains
    read-access to all its data for advisory and reporting purposes.
    """

    partner = models.ForeignKey(
        PartnerProfile, on_delete=models.CASCADE, related_name="clients"
    )
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="partner_managers"
    )
    # Referral tracking — did this partner bring this client on?
    is_referred = models.BooleanField(default=True)
    commission_earned = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    notes = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    linked_at = models.DateTimeField(auto_now_add=True)

    class Meta(TimeStampedModel.Meta):
        unique_together = [["partner", "organisation"]]
        verbose_name = "Partner Client"

    def __str__(self):
        return f"{self.partner.user.email} → {self.organisation.name}"
