import uuid
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_bulletproof_disable_rls'),
    ]

    operations = [
        migrations.CreateModel(
            name='IdempotencyRecord',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('user_id', models.UUIDField(db_index=True)),
                ('key', models.CharField(max_length=256)),
                ('response_body', models.TextField()),
                ('response_status', models.PositiveSmallIntegerField()),
                ('expires_at', models.DateTimeField(db_index=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'app_label': 'core',
                'unique_together': {('user_id', 'key')},
            },
        ),
    ]
