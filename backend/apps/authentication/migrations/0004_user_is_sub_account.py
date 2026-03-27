from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('authentication', '0003_user_mfa_fields'),
    ]
    operations = [
        migrations.AddField(
            model_name='user',
            name='is_sub_account',
            field=models.BooleanField(
                default=False,
                help_text='True for accounts created under a parent organisation. Cannot create orgs or manage billing.',
            ),
        ),
    ]
