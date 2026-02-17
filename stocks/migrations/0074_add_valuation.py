# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0073_add_investment_indicator'),
    ]

    operations = [
        migrations.AddField(
            model_name='info',
            name='valuation',
            field=models.TextField(blank=True, default='', help_text='가치평가 내용 (마크다운 형식)', verbose_name='가치평가'),
        ),
        migrations.AddField(
            model_name='info',
            name='valuation_updated_at',
            field=models.DateField(blank=True, help_text='가치평가 마지막 수정일', null=True, verbose_name='가치평가 업데이트일'),
        ),
    ]
