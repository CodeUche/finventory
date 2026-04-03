# Generated manually 2026-03-31

import django.db.models.deletion
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0015_add_onboarding_completed"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PartnerProfile",
            fields=[
                ("id", models.UUIDField(primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="partner_profile",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tier",
                    models.CharField(
                        choices=[
                            ("starter", "Partner Starter (10 clients)"),
                            ("pro", "Partner Pro (30 clients)"),
                            ("agency", "Partner Agency (Unlimited)"),
                        ],
                        default="starter",
                        max_length=20,
                    ),
                ),
                ("firm_name", models.CharField(blank=True, max_length=200)),
                ("firm_logo", models.ImageField(blank=True, null=True, upload_to="partner_logos/")),
                ("max_clients", models.PositiveIntegerField(default=10)),
                ("commission_rate", models.DecimalField(decimal_places=2, default=Decimal("5"), max_digits=5)),
                ("total_commission_earned", models.DecimalField(decimal_places=4, default=Decimal("0"), max_digits=15)),
                ("white_label_reports", models.BooleanField(default=False)),
                ("consolidated_reporting", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "verbose_name": "Partner Profile",
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="PartnerClientLink",
            fields=[
                ("id", models.UUIDField(primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "partner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="clients",
                        to="tenancy.partnerprofile",
                    ),
                ),
                (
                    "organisation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="partner_managers",
                        to="tenancy.organisation",
                    ),
                ),
                ("is_referred", models.BooleanField(default=True)),
                ("commission_earned", models.DecimalField(decimal_places=4, default=Decimal("0"), max_digits=15)),
                ("notes", models.CharField(blank=True, max_length=255)),
                ("is_active", models.BooleanField(default=True)),
                ("linked_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Partner Client",
                "unique_together": {("partner", "organisation")},
                "abstract": False,
            },
        ),
    ]
