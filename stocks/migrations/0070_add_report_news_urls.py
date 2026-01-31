from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0069_researchprompt_needs_attachment'),
    ]

    operations = [
        migrations.AddField(
            model_name='report',
            name='report_url',
            field=models.URLField(blank=True, default='', help_text='리포트 원문 URL', max_length=500, verbose_name='리포트 링크'),
        ),
        migrations.AddField(
            model_name='report',
            name='news_url',
            field=models.URLField(blank=True, default='', help_text='관련 뉴스 URL', max_length=500, verbose_name='뉴스 링크'),
        ),
        migrations.AddField(
            model_name='stockuploadedreport',
            name='report_url',
            field=models.URLField(blank=True, default='', help_text='리포트 원문 URL', max_length=500, verbose_name='리포트 링크'),
        ),
        migrations.AddField(
            model_name='stockuploadedreport',
            name='news_url',
            field=models.URLField(blank=True, default='', help_text='관련 뉴스 URL', max_length=500, verbose_name='뉴스 링크'),
        ),
    ]
