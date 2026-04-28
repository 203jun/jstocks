from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0117_add_key_briefing_opinion'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='info',
            name='quarter_analysis',
        ),
        migrations.RemoveField(
            model_name='info',
            name='quarter_analysis_updated_at',
        ),
        migrations.RemoveField(
            model_name='info',
            name='quarter_analysis_opinion',
        ),
    ]
