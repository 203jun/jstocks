from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0044_add_insight_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='info',
            name='analysis_updated_at',
            field=models.DateField(blank=True, null=True, help_text='기업분석 마지막 수정일', verbose_name='기업분석 업데이트일'),
        ),
        migrations.AddField(
            model_name='info',
            name='insight_updated_at',
            field=models.DateField(blank=True, null=True, help_text='인사이트 마지막 수정일', verbose_name='인사이트 업데이트일'),
        ),
        migrations.AddField(
            model_name='info',
            name='memo_updated_at',
            field=models.DateField(blank=True, null=True, help_text='메모 마지막 수정일', verbose_name='메모 업데이트일'),
        ),
    ]
