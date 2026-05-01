from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0119_remove_analysis_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='stockdiary',
            name='is_buy',
            field=models.BooleanField(default=False, help_text='해당 일자에 매수 발생 여부', verbose_name='매수'),
        ),
        migrations.AddField(
            model_name='stockdiary',
            name='is_sell',
            field=models.BooleanField(default=False, help_text='해당 일자에 매도 발생 여부', verbose_name='매도'),
        ),
    ]
