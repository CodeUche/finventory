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
from apps.core.models import SoftDeleteModel, TimeStampedModel, MoneyField


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
    # WHT small-payer exemption: organisations with annual turnover ≤ ₦25m are exempt from
    # deducting WHT on transactions ≤ ₦2m/month (WHT 2024 Regulations, s.14)
    annual_turnover = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True,
        help_text="Declared annual turnover (NGN). Used for WHT small-payer exemption threshold."
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
    onboarding_completed = models.BooleanField(default=False)
    # Drives the business-type-aware POS (retail / restaurant / pharmacy / laundry /
    # services). 'restaurant' unlocks the hospitality module (tables, KOT, order types).
    class BusinessType(models.TextChoices):
        GENERAL = 'general', 'General / Retail'
        RESTAURANT = 'restaurant', 'Restaurant / Bar / Hotel'
        PHARMACY = 'pharmacy', 'Pharmacy / Supermarket'
        LAUNDRY = 'laundry', 'Laundry'
        SERVICES = 'services', 'Services'
    business_type = models.CharField(
        max_length=20, choices=BusinessType.choices, default=BusinessType.GENERAL)
    # When True, transactions are rejected if required GL account mappings are missing.
    # Default ON: new orgs are seeded with a full COA and an auto-filled mapping, so
    # strict mode is satisfied out of the box and keeps the books correct from day one.
    # (Existing orgs keep whatever value they already have.)
    strict_gl_mode = models.BooleanField(default=True)
    # Fixed-asset policy. Items costing below the threshold are expensed, not
    # capitalised (default ₦100,000). Revaluation (IAS 16) is opt-in — SME default is
    # the cost model — and needs practitioner sign-off before enabling.
    fixed_asset_capitalisation_threshold = MoneyField(default=100000)
    fixed_asset_revaluation_enabled = models.BooleanField(default=False)
    # NTA-2025 capital-allowance engine. OFF until a licensed tax practitioner signs
    # off the rate table + qualifying rules — enabling it drives the CIT computation.
    capital_allowance_nta2025_enabled = models.BooleanField(default=False)

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
        # Employee self-service only. Sits below viewer and never reaches the
        # operator UI — an EMPLOYEE membership grants access to /me and nothing
        # else, enforced by IsEmployeeSelf rather than by ModulePermission.
        EMPLOYEE = "employee", "Employee (self-service)"
        # Messaging-only access for a partner contact who has NOT been granted
        # full advisory/accountant access to this client org. Sits below viewer
        # (see ROLE_HIERARCHY) so every existing role-gated endpoint refuses it
        # automatically — a PARTNER_CONTACT membership only ever reaches the
        # in-app messaging endpoints, enforced by IsConversationParticipant.
        PARTNER_CONTACT = "partner_contact", "Partner Contact (messaging only)"

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
    # Only ever set for memberships provisioned via the partner-access flow
    # (_provision_partner_membership in tenancy/views.py) — records the
    # PartnerAccessRequest.Scope this membership was granted under, so
    # messaging permission checks can tell an 'operational'-scope ACCOUNTANT
    # grant (payroll/salary access, no messaging) apart from a
    # 'messaging_only'/'both'-scope one, even though both can carry the same
    # role value. Blank for ordinary (non-partner) memberships.
    granted_scope = models.CharField(max_length=20, blank=True, default="")

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

    Every other role — manager, accountant, staff, viewer — starts with NO
    access to anything. There is no sensible default: a team member can reach
    only what has been explicitly granted to them. Each organisation decides
    for itself what a manager or an accountant ought to see, rather than
    inheriting an assumption from us.

      (no record) — no access at all
      none  — no access; module is hidden from the sidebar
      view  — read-only access
      write — can create new records but cannot edit/delete existing ones
      edit  — full create / edit / delete access

    Enforced in two places that must agree:
      frontend/src/hooks/useModuleAccess.ts  — hides menus and blocks routes
      apps/core/permissions.requires_module  — refuses the request itself

    Until H-2 only the browser applied this, so the ticks were a sign on a
    door rather than a lock: a member with HR unticked could still ask the
    server for the staff list and receive salaries, national ID numbers,
    pension numbers and bank details.

    An earlier version of this docstring said the admin "can override each
    module individually", which read as though access existed by default and
    ticks removed it. That was never what the product did, and it is not what
    it does now.
    """

    MODULE_CHOICES = [
        ('sales', 'Sales / Invoices'),
        ('purchases', 'Purchase Orders'),
        ('bills', 'Bills / Payables'),
        ('expenses', 'Expenses'),
        ('inventory', 'Inventory'),
        ('customers', 'Customers'),
        ('suppliers', 'Suppliers'),
        ('payroll', 'HR / Payroll'),
        # Separate from payroll so a line manager can approve time off without
        # being able to see anyone's salary.
        ('leave', 'Leave'),
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


class PartnerAccessRequest(TimeStampedModel):
    """
    Explicit bilateral consent record for a partner to access a client organisation.

    Two flows:
      1. Partner-initiated  — partner sends a request → org owner approves or rejects.
      2. Client-initiated   — org owner generates a one-time invite token → partner
                              accepts via that token (no separate approval step needed).

    Status lifecycle:
      pending   → approved  (creates/reactivates PartnerClientLink + Membership)
      pending   → rejected  (org owner declines; partner can withdraw or re-request)
      approved  → withdrawn (partner leaves; link + membership deactivated)
    """

    class Status(models.TextChoices):
        PENDING   = "pending",   "Pending"
        APPROVED  = "approved",  "Approved"
        REJECTED  = "rejected",  "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"

    partner = models.ForeignKey(
        PartnerProfile,
        on_delete=models.CASCADE,
        related_name="access_requests",
    )
    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name="partner_requests",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    request_message = models.CharField(
        max_length=300, blank=True,
        help_text="Optional message from the partner to the org owner.",
    )
    rejection_reason = models.CharField(
        max_length=200, blank=True,
        help_text="Optional reason given by the org owner when rejecting.",
    )
    # Client-initiated invite flow
    invite_token = models.UUIDField(
        null=True, blank=True, unique=True, db_index=True,
        help_text="One-time token generated by the org owner to invite a specific partner.",
    )
    invite_token_used = models.BooleanField(default=False)
    # Audit
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="partner_access_requests_sent",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="partner_access_requests_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Scope(models.TextChoices):
        OPERATIONAL     = "operational",     "Operational (full advisory access)"
        MESSAGING_ONLY  = "messaging_only",  "Messaging Only"
        BOTH            = "both",            "Operational + Messaging"

    scope = models.CharField(
        max_length=20,
        choices=Scope.choices,
        default=Scope.OPERATIONAL,
        help_text=(
            "What access this request grants once approved. 'messaging_only' "
            "provisions a PARTNER_CONTACT membership (in-app messaging only, no "
            "operational data access); 'operational' and 'both' preserve the "
            "existing accountant-role provisioning behaviour."
        ),
    )

    class Meta(TimeStampedModel.Meta):
        unique_together = [["partner", "organisation"]]
        verbose_name = "Partner Access Request"

    def __str__(self):
        return f"{self.partner.user.email} → {self.organisation.name} ({self.status})"


# ─── Commission Credit Wallet ────────────────────────────────────────────────

class CommissionLedger(TimeStampedModel):
    """
    Append-only audit log for partner commission credits.

    Rows are NEVER updated or deleted after insert.
    Balance = SUM(commission_amount) for confirmed rows.
    Negative rows (event_type=credit_applied) represent credits spent on subscriptions.
    """

    class EventType(models.TextChoices):
        SUBSCRIPTION_PAYMENT = "subscription_payment", "Subscription Payment"
        TRIAL_CONVERSION     = "trial_conversion",     "Trial Conversion"
        REFERRAL_BONUS       = "referral_bonus",       "Referral Bonus"
        CREDIT_APPLIED       = "credit_applied",       "Credit Applied to Subscription"
        REVERSAL             = "reversal",             "Reversal (Chargeback)"

    class Status(models.TextChoices):
        PENDING   = "pending",   "Pending (within chargeback window)"
        CONFIRMED = "confirmed", "Confirmed"

    partner_profile  = models.ForeignKey(PartnerProfile, on_delete=models.CASCADE, related_name="commission_ledger")
    client_org       = models.ForeignKey(Organisation, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    event_type       = models.CharField(max_length=30, choices=EventType.choices)
    gross_amount     = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    commission_rate  = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    commission_amount = models.DecimalField(max_digits=15, decimal_places=4)
    currency         = models.CharField(max_length=3, default="NGN")
    reference        = models.CharField(max_length=255, blank=True, db_index=True)
    period_start     = models.DateField(null=True, blank=True)
    period_end       = models.DateField(null=True, blank=True)
    status           = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    applied_to_sub   = models.ForeignKey(
        "subscriptions.Subscription", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="commission_credits",
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = "Commission Ledger Entry"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["partner_profile", "status"]),
            models.Index(fields=["reference"]),
        ]

    def __str__(self):
        return f"{self.partner_profile} | {self.event_type} | {self.commission_amount} {self.currency}"


# ─── Partner Invoices ────────────────────────────────────────────────────────

class PartnerInvoice(TimeStampedModel):
    """
    Invoice issued BY a partner TO one of their managed client organisations
    for professional services (retainer, bookkeeping fees, etc.).

    Deliberately isolated from the main Invoice model to avoid cross-tenant
    contamination. No stock, warehouse, or product dependencies.
    """

    class Status(models.TextChoices):
        DRAFT    = "draft",    "Draft"
        SENT     = "sent",     "Sent"
        PAID     = "paid",     "Paid"
        OVERDUE  = "overdue",  "Overdue"
        VOID     = "void",     "Void"

    class PaymentMethod(models.TextChoices):
        BANK_TRANSFER = "bank_transfer", "Bank Transfer"
        CASH          = "cash",          "Cash"
        POS           = "pos",           "POS"

    partner_profile  = models.ForeignKey(PartnerProfile, on_delete=models.CASCADE, related_name="partner_invoices")
    client_org       = models.ForeignKey(Organisation, on_delete=models.PROTECT, related_name="received_partner_invoices")
    invoice_number   = models.CharField(max_length=30, blank=True, db_index=True)
    status           = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    issue_date       = models.DateField()
    due_date         = models.DateField()
    currency         = models.CharField(max_length=3, default="NGN")
    subtotal         = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    tax_rate         = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax_amount       = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total            = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    paid_at          = models.DateTimeField(null=True, blank=True)
    payment_method   = models.CharField(max_length=20, choices=PaymentMethod.choices, blank=True)
    notes            = models.TextField(blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = "Partner Invoice"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            prefix = str(self.partner_profile_id).replace("-", "").upper()[:4]
            last = PartnerInvoice.objects.filter(partner_profile=self.partner_profile).count()
            self.invoice_number = f"PAR-{prefix}-{str(last + 1).zfill(6)}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.invoice_number} → {self.client_org.name}"


class PartnerInvoiceItem(TimeStampedModel):
    invoice     = models.ForeignKey(PartnerInvoice, on_delete=models.CASCADE, related_name="items")
    description = models.CharField(max_length=255)
    quantity    = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price  = models.DecimalField(max_digits=15, decimal_places=2)
    total       = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    sort_order  = models.PositiveIntegerField(default=0)

    class Meta(TimeStampedModel.Meta):
        ordering = ["sort_order"]

    def save(self, *args, **kwargs):
        self.total = self.quantity * self.unit_price
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.invoice.invoice_number} | {self.description}"


# ─── White-label Configuration ───────────────────────────────────────────────

class WhiteLabelConfig(TimeStampedModel):
    """
    Custom domain + branding for Agency-tier partners.

    Verification flow:
      1. Partner saves custom_domain → verification_token is generated.
      2. Partner adds DNS TXT: _audity-verify.<domain> = <token>
      3. Partner calls /verify_domain/ → DNS lookup confirms ownership.
      4. Platform admin flips ssl_active=True after infra is ready.
    """

    partner_profile     = models.OneToOneField(PartnerProfile, on_delete=models.CASCADE, related_name="white_label")
    custom_domain       = models.CharField(max_length=253, unique=True, null=True, blank=True, db_index=True)
    is_domain_verified  = models.BooleanField(default=False)
    verification_token  = models.CharField(max_length=64, blank=True)
    ssl_active          = models.BooleanField(default=False)
    # Branding
    brand_name          = models.CharField(max_length=100, blank=True)
    logo_url            = models.URLField(blank=True)
    favicon_url         = models.URLField(blank=True)
    primary_color       = models.CharField(max_length=7, blank=True, help_text="#hex colour")
    login_tagline       = models.CharField(max_length=200, blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = "White-label Config"

    def save(self, *args, **kwargs):
        import secrets
        # Re-generate token whenever domain changes (reset verification)
        try:
            old = WhiteLabelConfig.objects.get(pk=self.pk)
            if old.custom_domain != self.custom_domain:
                self.verification_token = secrets.token_hex(32)
                self.is_domain_verified = False
        except WhiteLabelConfig.DoesNotExist:
            if not self.verification_token:
                self.verification_token = secrets.token_hex(32)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"WhiteLabel: {self.partner_profile} → {self.custom_domain or '(none)'}"
