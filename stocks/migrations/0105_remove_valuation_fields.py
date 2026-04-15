from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0104_add_base_quarter_fields'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='info',
            name='valuation',
        ),
        migrations.RemoveField(
            model_name='info',
            name='valuation_updated_at',
        ),
    ]
