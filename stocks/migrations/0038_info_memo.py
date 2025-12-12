from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0037_delete_cronjob'),
    ]

    operations = [
        migrations.AddField(
            model_name='info',
            name='memo',
            field=models.TextField(blank=True, default='', help_text='자유 메모 (HTML 형식)', verbose_name='메모'),
        ),
    ]
