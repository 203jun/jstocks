# -*- coding: utf-8 -*-
"""
ETF 에도 '추적' 을 둔다.

종목과 ETF 의 이름 밑 배지를 세 칸으로 고정한다 — 시장 / 분류 / 추적.
칸이 늘 같은 자리에 있어야 눈이 찾아가지 않는다. ETF 에는 추적 값이
없어서 셋째 칸을 채울 수 없었다.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0157_drop_sector_event'),
    ]

    operations = [
        migrations.AddField(
            model_name='infoetf',
            name='is_tracking',
            field=models.BooleanField(default=False, help_text='단기 매매를 위해 추적 중인 ETF 여부', verbose_name='추적중'),
        ),
    ]
