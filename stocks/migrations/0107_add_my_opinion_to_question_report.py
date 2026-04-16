from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0106_add_supply_demand_analysis'),
    ]

    operations = [
        migrations.AddField(
            model_name='stockquestionreport',
            name='my_opinion',
            field=models.TextField(blank=True, default='', help_text='이 리서치에 대한 나의 의견 (텍스트)', verbose_name='내생각'),
        ),
    ]
