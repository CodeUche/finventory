# Generated migration for AIReconMatch model

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0002_bankreconciliation_bankreconciliationline_and_more"),
        ("tenancy", "0003_organisation_bank_account_name_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="AIReconMatch",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_deleted", models.BooleanField(db_index=True, default=False)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("confidence", models.FloatField(default=0.0)),
                (
                    "match_type",
                    models.CharField(
                        choices=[
                            ("exact", "Exact Match"),
                            ("fuzzy", "Fuzzy Match"),
                            ("uncertain", "Uncertain"),
                        ],
                        default="uncertain",
                        max_length=20,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("proposed", "Proposed"),
                            ("confirmed", "Confirmed"),
                            ("rejected", "Rejected"),
                        ],
                        default="proposed",
                        max_length=20,
                    ),
                ),
                ("ai_reasoning", models.TextField(blank=True)),
                ("ai_advice", models.TextField(blank=True)),
                ("matched_at", models.DateTimeField(blank=True, null=True)),
                (
                    "bank_line",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_matches",
                        to="accounting.bankreconciliationline",
                    ),
                ),
                (
                    "book_line",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ai_matches",
                        to="accounting.journalline",
                    ),
                ),
                (
                    "organisation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="%(app_label)s_%(class)s_set",
                        to="tenancy.organisation",
                    ),
                ),
                (
                    "reconciliation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_matches",
                        to="accounting.bankreconciliation",
                    ),
                ),
            ],
            options={
                "ordering": ["-confidence"],
            },
        ),
    ]
