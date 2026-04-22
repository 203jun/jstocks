from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0110_add_my_opinion_to_reports'),
    ]

    operations = [
        migrations.AddField(
            model_name='info',
            name='is_tracking',
            field=models.BooleanField(default=False, help_text='단기 매매를 위해 추적 중인 종목 여부', verbose_name='추적중'),
        ),
    ]
