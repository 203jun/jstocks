from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0035_add_youtube_video_summary'),
    ]

    operations = [
        migrations.AddField(
            model_name='cronjob',
            name='command_type',
            field=models.CharField(
                choices=[('command', 'Django 명령어'), ('script', '쉘 스크립트')],
                default='command',
                help_text='command: Django 명령어, script: 쉘 스크립트',
                max_length=10,
                verbose_name='작업유형'
            ),
        ),
    ]
