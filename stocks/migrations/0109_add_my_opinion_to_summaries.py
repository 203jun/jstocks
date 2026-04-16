from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0108_add_analysis_opinions'),
    ]

    operations = [
        # News
        migrations.AddField(
            model_name='news',
            name='my_opinion',
            field=models.TextField(blank=True, default='', verbose_name='내생각'),
        ),
        # Nodaji
        migrations.AddField(
            model_name='nodaji',
            name='my_opinion',
            field=models.TextField(blank=True, default='', verbose_name='내생각'),
        ),
        # YoutubeVideo: note -> my_opinion
        migrations.RemoveField(
            model_name='youtubevideo',
            name='note',
        ),
        migrations.AddField(
            model_name='youtubevideo',
            name='my_opinion',
            field=models.TextField(blank=True, default='', verbose_name='내생각'),
        ),
        # SectorNews
        migrations.AddField(
            model_name='sectornews',
            name='my_opinion',
            field=models.TextField(blank=True, default='', verbose_name='내생각'),
        ),
        # SectorYoutubeVideo: note -> my_opinion
        migrations.RemoveField(
            model_name='sectoryoutubevideo',
            name='note',
        ),
        migrations.AddField(
            model_name='sectoryoutubevideo',
            name='my_opinion',
            field=models.TextField(blank=True, default='', verbose_name='내생각'),
        ),
    ]
