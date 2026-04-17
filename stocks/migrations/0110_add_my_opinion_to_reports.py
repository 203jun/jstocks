from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0109_add_my_opinion_to_summaries'),
    ]

    operations = [
        migrations.AddField(
            model_name='report',
            name='my_opinion',
            field=models.TextField(blank=True, default='', help_text='리포트에 대한 나의 의견', verbose_name='내생각'),
        ),
        migrations.AddField(
            model_name='stockuploadedreport',
            name='my_opinion',
            field=models.TextField(blank=True, default='', help_text='리포트에 대한 나의 의견', verbose_name='내생각'),
        ),
    ]
