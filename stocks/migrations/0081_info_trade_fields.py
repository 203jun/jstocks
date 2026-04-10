from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0080_youtubevideo_note'),
    ]

    operations = [
        migrations.AddField(
            model_name='info',
            name='buy_reason',
            field=models.TextField(blank=True, default='', verbose_name='매수근거'),
        ),
        migrations.AddField(
            model_name='info',
            name='sell_reason',
            field=models.TextField(blank=True, default='', verbose_name='매도근거'),
        ),
        migrations.AddField(
            model_name='info',
            name='buy_price',
            field=models.IntegerField(blank=True, null=True, verbose_name='매수가'),
        ),
        migrations.AddField(
            model_name='info',
            name='sell_price',
            field=models.IntegerField(blank=True, null=True, verbose_name='매도가'),
        ),
        migrations.AddField(
            model_name='info',
            name='trade_updated_at',
            field=models.DateField(blank=True, null=True, verbose_name='매매근거 업데이트일'),
        ),
    ]
