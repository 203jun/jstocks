from django.db import migrations, models


def merge_incubator_to_normal(apps, schema_editor):
    Info = apps.get_model('stocks', 'Info')
    Info.objects.filter(interest_level='incubator').update(interest_level='normal')


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0082_info_buy_price_range'),
    ]

    operations = [
        migrations.RunPython(merge_incubator_to_normal, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='info',
            name='interest_level',
            field=models.CharField(
                max_length=10,
                choices=[('super', '초관심'), ('normal', '관심')],
                null=True, blank=True,
                verbose_name='관심단계',
            ),
        ),
    ]
