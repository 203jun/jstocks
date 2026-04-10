from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0081_info_trade_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='info',
            name='buy_price_range',
            field=models.IntegerField(default=5, verbose_name='매수가 범위(%)'),
        ),
    ]
