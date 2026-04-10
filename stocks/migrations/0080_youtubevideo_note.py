from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0079_stockdiary'),
    ]

    operations = [
        migrations.AddField(
            model_name='youtubevideo',
            name='note',
            field=models.CharField(blank=True, max_length=200, verbose_name='한줄 메모'),
        ),
    ]
