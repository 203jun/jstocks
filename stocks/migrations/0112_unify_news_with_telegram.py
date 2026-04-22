from django.db import migrations, models


def migrate_telegram_to_news(apps, schema_editor):
    News = apps.get_model('stocks', 'News')
    SectorNews = apps.get_model('stocks', 'SectorNews')
    TelegramMessage = apps.get_model('stocks', 'TelegramMessage')
    SectorTelegramMessage = apps.get_model('stocks', 'SectorTelegramMessage')

    for msg in TelegramMessage.objects.all():
        source = msg.channel_name or msg.channel
        published = f"{msg.date} {msg.time}".strip()
        News.objects.create(
            stock=msg.stock,
            title='',
            link='',
            content=msg.text,
            source=source,
            published=published,
            summary=msg.summary,
        )

    for msg in SectorTelegramMessage.objects.all():
        source = msg.channel_name or msg.channel
        published = f"{msg.date} {msg.time}".strip()
        SectorNews.objects.create(
            sector=msg.sector,
            title='',
            link='',
            content=msg.text,
            source=source,
            published=published,
            summary=msg.summary,
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0111_add_is_tracking_field'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='news',
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name='sectornews',
            unique_together=set(),
        ),
        migrations.AlterField(
            model_name='news',
            name='title',
            field=models.CharField(blank=True, max_length=500, verbose_name='제목'),
        ),
        migrations.AlterField(
            model_name='news',
            name='link',
            field=models.URLField(blank=True, max_length=1000, verbose_name='링크'),
        ),
        migrations.AddField(
            model_name='news',
            name='content',
            field=models.TextField(blank=True, help_text='텔레그램 메시지 등 본문', verbose_name='내용'),
        ),
        migrations.AlterField(
            model_name='sectornews',
            name='title',
            field=models.CharField(blank=True, max_length=500, verbose_name='제목'),
        ),
        migrations.AlterField(
            model_name='sectornews',
            name='link',
            field=models.URLField(blank=True, max_length=1000, verbose_name='링크'),
        ),
        migrations.AddField(
            model_name='sectornews',
            name='content',
            field=models.TextField(blank=True, help_text='텔레그램 메시지 등 본문', verbose_name='내용'),
        ),
        migrations.RunPython(migrate_telegram_to_news, noop_reverse),
    ]
