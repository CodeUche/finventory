from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('authentication', '0004_user_is_sub_account'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='must_change_password',
            field=models.BooleanField(
                default=False,
                help_text='Forces a password change on next login. Set True for new sub-accounts.',
            ),
        ),
    ]
