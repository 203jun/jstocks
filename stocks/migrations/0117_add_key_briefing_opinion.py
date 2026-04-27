from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0116_add_quick_report'),
    ]

    operations = [
        migrations.AddField(
            model_name='info',
            name='key_briefing_opinion',
            field=models.TextField(blank=True, default='', verbose_name='핵심브리핑 요약'),
        ),
    ]
