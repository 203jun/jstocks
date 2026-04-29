from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0118_remove_quarter_analysis_fields'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='info',
            name='analysis_text',
        ),
        migrations.RemoveField(
            model_name='info',
            name='analysis_type',
        ),
        migrations.RemoveField(
            model_name='info',
            name='analysis_updated_at',
        ),
    ]
