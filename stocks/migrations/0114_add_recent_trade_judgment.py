from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0113_move_telegram_content_to_summary'),
    ]

    operations = [
        migrations.AddField(
            model_name='info',
            name='recent_trade_judgment',
            field=models.TextField(blank=True, default='', help_text='AI 매매 판단 결과 저장', verbose_name='최근매매판별'),
        ),
    ]
