# -*- coding: utf-8 -*-
"""
ETF 이벤트를 없앤다. 0건이다 — 만들고 한 번도 안 썼다.

종목 이벤트는 0153 에서 리서치 칸으로 내려갔다. 이벤트 기능 자체를 안 쓰기로
했으므로 ETF 쪽도 지운다.

메인 화면의 'D-10 이내 이벤트'에는 이제 섹터만 남는다. 섹터도 0건이라
그 자리는 늘 비어 있다.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0155_regroup_research'),
    ]

    operations = [
        migrations.DeleteModel(
            name='ETFEvent',
        ),
    ]
