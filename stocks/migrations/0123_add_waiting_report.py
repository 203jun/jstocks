from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0122_add_waiting_interest_level'),
    ]

    operations = [
        migrations.CreateModel(
            name='WaitingReport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('question', models.CharField(max_length=200, verbose_name='질문')),
                ('prompt', models.TextField(blank=True, verbose_name='프롬프트')),
                ('order', models.IntegerField(default=0, verbose_name='순서')),
                ('needs_attachment', models.BooleanField(default=False, verbose_name='첨부파일 필요')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='생성일시')),
            ],
            options={
                'verbose_name': '대기',
                'verbose_name_plural': '대기',
                'db_table': 'waiting_report',
                'ordering': ['order', 'id'],
            },
        ),
    ]
