# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0072_add_financial_analysis'),
    ]

    operations = [
        migrations.AddField(
            model_name='info',
            name='investment_indicator',
            field=models.TextField(blank=True, default='', help_text='투자지표 내용 (마크다운 형식)', verbose_name='투자지표'),
        ),
        migrations.AddField(
            model_name='info',
            name='investment_indicator_updated_at',
            field=models.DateField(blank=True, help_text='투자지표 마지막 수정일', null=True, verbose_name='투자지표 업데이트일'),
        ),
    ]
