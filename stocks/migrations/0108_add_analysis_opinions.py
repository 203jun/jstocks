from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0107_add_my_opinion_to_question_report'),
    ]

    operations = [
        migrations.AddField(
            model_name='info',
            name='financial_analysis_v2_opinion',
            field=models.TextField(blank=True, default='', verbose_name='재무분석 내생각'),
        ),
        migrations.AddField(
            model_name='info',
            name='consensus_analysis_opinion',
            field=models.TextField(blank=True, default='', verbose_name='컨센서스분석 내생각'),
        ),
        migrations.AddField(
            model_name='info',
            name='quarter_analysis_opinion',
            field=models.TextField(blank=True, default='', verbose_name='직전분기재무해석 내생각'),
        ),
        migrations.AddField(
            model_name='info',
            name='supply_demand_analysis_opinion',
            field=models.TextField(blank=True, default='', verbose_name='수급분석 내생각'),
        ),
    ]
