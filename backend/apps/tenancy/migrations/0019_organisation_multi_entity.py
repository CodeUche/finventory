from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [
        ('tenancy', '0018_add_referral_code_to_partner'),
    ]
    operations = [
        migrations.AddField(
            model_name='organisation',
            name='parent_org',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='child_entities',
                to='tenancy.organisation',
                help_text='Parent organisation for multi-entity groups (Enterprise only).',
            ),
        ),
        migrations.AddField(
            model_name='organisation',
            name='entity_group_name',
            field=models.CharField(
                blank=True, max_length=100,
                help_text="Short label for this entity within the group.",
            ),
        ),
    ]
