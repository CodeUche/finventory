"""
Initial migration for apps.einvoicing.

Creates:
    einvoicing_firsconfig       — per-org DigiTax credentials + enrollment state
    einvoicing_firssubmission   — append-only submission audit log
"""

import django.db.models.deletion
import django.utils.timezone
import uuid

from django.db import migrations, models

import apps.core.fields


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("sales", "0013_alter_location_created_at"),
        ("tenancy", "0004_modulepermission"),
    ]

    operations = [
        migrations.CreateModel(
            name="FirsConfig",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "organisation",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="firs_config",
                        to="tenancy.organisation",
                    ),
                ),
                ("is_enrolled", models.BooleanField(default=False, help_text="Master switch — no FIRS submissions until this is True.")),
                ("tin", models.CharField(blank=True, max_length=20, help_text="Organisation Tax Identification Number for FIRS.")),
                ("business_name", models.CharField(blank=True, max_length=255, help_text="Legal business name as registered with FIRS.")),
                ("app_api_key", apps.core.fields.EncryptedCharField(blank=True, max_length=300, help_text="DigiTax x-api-key — encrypted at rest, never exposed in API responses.")),
                ("app_base_url", models.CharField(default="https://api.digitax.tech/ng/v1", max_length=500)),
                ("use_sandbox", models.BooleanField(default=True, help_text="Route submissions to DigiTax sandbox. Set False only for production go-live.")),
                ("digitax_party_id", models.CharField(blank=True, max_length=100, help_text="DigiTax-assigned party ID for this organisation (seller). Cached after first registration.")),
                ("enrolled_at", models.DateTimeField(blank=True, null=True)),
                ("last_test_at", models.DateTimeField(blank=True, null=True)),
                ("last_test_ok", models.BooleanField(null=True, help_text="Result of the most recent test-connection attempt.")),
            ],
            options={
                "verbose_name": "FIRS Config",
                "verbose_name_plural": "FIRS Configs",
                "ordering": ["-created_at"],
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="FirsSubmission",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_deleted", models.BooleanField(db_index=True, default=False)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "organisation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="einvoicing_firssubmission_set",
                        to="tenancy.organisation",
                    ),
                ),
                (
                    "invoice",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="firs_submissions",
                        to="sales.invoice",
                    ),
                ),
                ("submission_ref", models.CharField(blank=True, db_index=True, max_length=200, help_text="DigiTax-assigned submission reference returned after POST /invoices.")),
                (
                    "transaction_type",
                    models.CharField(
                        blank=True,
                        choices=[("B2B", "Business to Business"), ("B2G", "Business to Government"), ("B2C", "Business to Consumer")],
                        max_length=3,
                        help_text="B2B | B2G | B2C — resolved from customer data at submission time.",
                    ),
                ),
                ("payload_json", models.JSONField(default=dict, help_text="Exact JSON payload sent to DigiTax POST /invoices.")),
                ("response_raw", models.JSONField(default=dict, help_text="Raw JSON response body from DigiTax.")),
                ("irn", models.CharField(blank=True, max_length=200, help_text="FIRS Invoice Reference Number — format: XXXXXXXXXX-XXXXXXXX-YYYYMMDD")),
                ("csid", models.CharField(blank=True, max_length=500, help_text="Cryptographic Stamp Identifier returned by DigiTax.")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("submitted", "Submitted to DigiTax"),
                            ("cleared", "IRN Issued (Cleared)"),
                            ("reported", "B2C Batch Reported"),
                            ("failed", "Submission Failed"),
                            ("bypassed", "Bypassed (B2C daily batch)"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("attempt_count", models.PositiveSmallIntegerField(default=1, help_text="Incremented each time this submission row is retried.")),
                ("last_attempted_at", models.DateTimeField(auto_now=True)),
                ("error_detail", models.TextField(blank=True, help_text="Human-readable error from DigiTax or internal exception.")),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("cleared_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "verbose_name": "FIRS Submission",
                "verbose_name_plural": "FIRS Submissions",
                "ordering": ["-created_at"],
                "abstract": False,
            },
        ),
        migrations.AddIndex(
            model_name="firssubmission",
            index=models.Index(fields=["invoice", "status"], name="einvoicing_invoice_status_idx"),
        ),
        migrations.AddIndex(
            model_name="firssubmission",
            index=models.Index(fields=["organisation", "status", "created_at"], name="einvoicing_org_status_date_idx"),
        ),
        migrations.AddIndex(
            model_name="firssubmission",
            index=models.Index(fields=["submission_ref"], name="einvoicing_submission_ref_idx"),
        ),
    ]
