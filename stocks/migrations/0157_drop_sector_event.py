# -*- coding: utf-8 -*-
"""
섹터 이벤트를 없애고 이벤트 기능을 끝낸다. 0건이다.

    종목 이벤트   0153  리서치 '이벤트' 칸으로 내려감 (4건)
    ETF 이벤트    0156  삭제 (0건)
    섹터 이벤트   여기  삭제 (0건)

메인 화면의 'D-10 이내 이벤트' 블록도 같이 걷어낸다. 남길 이유가 없다 —
셋 중 둘은 0건이었고 하나는 리서치 글이 되어 날짜로 뽑을 수 없다.

앞으로 예정된 일정은 리서치 '이벤트' 칸에서 본다. 날짜별 알림이 아니라
"앞으로 무엇이 예정돼 있나"를 한 번에 읽는 글이다.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0156_drop_etf_event'),
    ]

    operations = [
        migrations.DeleteModel(
            name='SectorEvent',
        ),
    ]
