from django.db import migrations


def move_content_to_summary(apps, schema_editor):
    News = apps.get_model('stocks', 'News')
    SectorNews = apps.get_model('stocks', 'SectorNews')

    for news in News.objects.filter(link='').exclude(content=''):
        if news.summary:
            news.summary = f"{news.content}\n\n{news.summary}"
        else:
            news.summary = news.content
        news.content = ''
        news.save(update_fields=['summary', 'content'])

    for news in SectorNews.objects.filter(link='').exclude(content=''):
        if news.summary:
            news.summary = f"{news.content}\n\n{news.summary}"
        else:
            news.summary = news.content
        news.content = ''
        news.save(update_fields=['summary', 'content'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0112_unify_news_with_telegram'),
    ]

    operations = [
        migrations.RunPython(move_content_to_summary, noop_reverse),
    ]
