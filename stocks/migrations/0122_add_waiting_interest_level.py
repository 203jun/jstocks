from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0121_add_summary_report'),
    ]

    operations = [
        migrations.AlterField(
            model_name='info',
            name='interest_level',
            field=models.CharField(blank=True, choices=[('super', '초관심'), ('normal', '관심'), ('waiting', '대기')], help_text='투자 관심 단계 (초관심 > 관심 > 대기)', max_length=10, null=True, verbose_name='관심단계'),
        ),
    ]
