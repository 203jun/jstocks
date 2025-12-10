from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0036_add_cronjob_command_type'),
    ]

    operations = [
        migrations.DeleteModel(
            name='CronJob',
        ),
    ]
