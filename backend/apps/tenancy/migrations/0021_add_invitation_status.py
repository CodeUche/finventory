from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenancy', '0020_alter_organisation_entity_group_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='invitation',
            name='is_rejected',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='invitation',
            name='module_permissions',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Optional per-module access overrides: {"sales": "edit", "reports": "view", ...}',
            ),
        ),
    ]
