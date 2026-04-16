from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0105_remove_valuation_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='info',
            name='supply_demand_analysis',
            field=models.TextField(blank=True, default='', help_text='수급분석 내용 (마크다운 형식)', verbose_name='수급분석'),
        ),
        migrations.AddField(
            model_name='info',
            name='supply_demand_analysis_updated_at',
            field=models.DateField(blank=True, help_text='수급분석 마지막 수정일', null=True, verbose_name='수급분석 업데이트일'),
        ),
    ]
