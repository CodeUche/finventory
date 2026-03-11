from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenancy', '0004_modulepermission'),
    ]

    operations = [
        migrations.AddField(
            model_name='organisation',
            name='letterhead',
            field=models.ImageField(
                blank=True,
                help_text='Optional letterhead image shown at the top of invoices and PDF documents',
                null=True,
                upload_to='org_letterheads/',
            ),
        ),
    ]
