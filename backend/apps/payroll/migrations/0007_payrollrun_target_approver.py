import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payroll", "0006_bonus_attendance_transfer_approval"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="payrollrun",
            name="target_approver",
            field=models.ForeignKey(
                blank=True,
                help_text="The specific admin/owner the submitter directed this approval to",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="payroll_runs_to_approve",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
