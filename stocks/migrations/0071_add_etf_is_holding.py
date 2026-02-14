# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0070_add_report_news_urls'),
    ]

    operations = [
        migrations.AddField(
            model_name='infoetf',
            name='is_holding',
            field=models.BooleanField(default=False, help_text='현재 보유 중인 ETF 여부', verbose_name='보유중'),
        ),
    ]
