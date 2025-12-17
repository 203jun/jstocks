from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0043_add_analysis_text'),
    ]

    operations = [
        # 새 필드 추가
        migrations.AddField(
            model_name='info',
            name='insight_summary_html',
            field=models.TextField(blank=True, default='', help_text='투자포인트/리스크/일정 요약 (HTML 형식)', verbose_name='인사이트(요약)'),
        ),
        migrations.AddField(
            model_name='info',
            name='insight_report_html',
            field=models.TextField(blank=True, default='', help_text='투자포인트/리스크/일정 상세 리포트 (HTML 형식)', verbose_name='인사이트(리포트)'),
        ),
        # 기존 필드 삭제
        migrations.RemoveField(
            model_name='info',
            name='investment_point',
        ),
        migrations.RemoveField(
            model_name='info',
            name='risk',
        ),
    ]
