"""
Migration: CommissionLedger, PartnerInvoice, PartnerInvoiceItem, WhiteLabelConfig
"""
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0025_partner_access_request"),
        ("subscriptions", "0017_partner_trial_30_days"),
    ]

    operations = [
        # ── CommissionLedger ──────────────────────────────────────────────────
        migrations.CreateModel(
            name="CommissionLedger",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("partner_profile", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="commission_ledger", to="tenancy.partnerprofile")),
                ("client_org", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="tenancy.organisation")),
                ("applied_to_sub", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="commission_credits", to="subscriptions.subscription")),
                ("event_type", models.CharField(choices=[("subscription_payment", "Subscription Payment"), ("trial_conversion", "Trial Conversion"), ("referral_bonus", "Referral Bonus"), ("credit_applied", "Credit Applied to Subscription"), ("reversal", "Reversal (Chargeback)")], max_length=30)),
                ("gross_amount", models.DecimalField(decimal_places=4, default=0, max_digits=15)),
                ("commission_rate", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("commission_amount", models.DecimalField(decimal_places=4, max_digits=15)),
                ("currency", models.CharField(default="NGN", max_length=3)),
                ("reference", models.CharField(blank=True, db_index=True, max_length=255)),
                ("period_start", models.DateField(blank=True, null=True)),
                ("period_end", models.DateField(blank=True, null=True)),
                ("status", models.CharField(choices=[("pending", "Pending (within chargeback window)"), ("confirmed", "Confirmed")], db_index=True, default="pending", max_length=20)),
            ],
            options={"verbose_name": "Commission Ledger Entry", "ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="commissionledger",
            index=models.Index(fields=["partner_profile", "status"], name="comm_ledger_partner_status_idx"),
        ),
        migrations.AddIndex(
            model_name="commissionledger",
            index=models.Index(fields=["reference"], name="comm_ledger_reference_idx"),
        ),

        # ── PartnerInvoice ────────────────────────────────────────────────────
        migrations.CreateModel(
            name="PartnerInvoice",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("partner_profile", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="partner_invoices", to="tenancy.partnerprofile")),
                ("client_org", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="received_partner_invoices", to="tenancy.organisation")),
                ("invoice_number", models.CharField(blank=True, db_index=True, max_length=30)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("sent", "Sent"), ("paid", "Paid"), ("overdue", "Overdue"), ("void", "Void")], default="draft", max_length=20)),
                ("issue_date", models.DateField()),
                ("due_date", models.DateField()),
                ("currency", models.CharField(default="NGN", max_length=3)),
                ("subtotal", models.DecimalField(decimal_places=2, default=0, max_digits=15)),
                ("tax_rate", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("tax_amount", models.DecimalField(decimal_places=2, default=0, max_digits=15)),
                ("total", models.DecimalField(decimal_places=2, default=0, max_digits=15)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("payment_method", models.CharField(blank=True, choices=[("bank_transfer", "Bank Transfer"), ("cash", "Cash"), ("pos", "POS")], max_length=20)),
                ("notes", models.TextField(blank=True)),
            ],
            options={"verbose_name": "Partner Invoice", "ordering": ["-created_at"]},
        ),

        # ── PartnerInvoiceItem ────────────────────────────────────────────────
        migrations.CreateModel(
            name="PartnerInvoiceItem",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("invoice", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="tenancy.partnerinvoice")),
                ("description", models.CharField(max_length=255)),
                ("quantity", models.DecimalField(decimal_places=2, default=1, max_digits=10)),
                ("unit_price", models.DecimalField(decimal_places=2, max_digits=15)),
                ("total", models.DecimalField(decimal_places=2, default=0, max_digits=15)),
                ("sort_order", models.PositiveIntegerField(default=0)),
            ],
            options={"ordering": ["sort_order"]},
        ),

        # ── WhiteLabelConfig ──────────────────────────────────────────────────
        migrations.CreateModel(
            name="WhiteLabelConfig",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("partner_profile", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="white_label", to="tenancy.partnerprofile")),
                ("custom_domain", models.CharField(blank=True, db_index=True, max_length=253, null=True, unique=True)),
                ("is_domain_verified", models.BooleanField(default=False)),
                ("verification_token", models.CharField(blank=True, max_length=64)),
                ("ssl_active", models.BooleanField(default=False)),
                ("brand_name", models.CharField(blank=True, max_length=100)),
                ("logo_url", models.URLField(blank=True)),
                ("favicon_url", models.URLField(blank=True)),
                ("primary_color", models.CharField(blank=True, help_text="#hex colour", max_length=7)),
                ("login_tagline", models.CharField(blank=True, max_length=200)),
            ],
            options={"verbose_name": "White-label Config"},
        ),
    ]
