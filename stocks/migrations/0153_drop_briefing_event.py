# -*- coding: utf-8 -*-
"""
핵심브리핑과 종목 이벤트의 옛 자리를 없앤다. 0152 가 리서치 칸을 만든다.

  Info.key_briefing            관심종목 47개 중 30개, 마지막 갱신 2026-04-20
  Info.key_briefing_updated_at
  Info.key_briefing_opinion    1건 (my_opinion 과 같은 죽은 칸이었다)
  StockEvent                   4건
  Schedule                     0건 — 만들고 한 번도 안 썼다

내용은 옮기지 않는다. 넉 달 된 것들이고, 프롬프트를 한 번 돌리면 지금
자료로 다시 채워진다.

StockEvent 가 빠지면서 메인 화면의 'D-10 이내 이벤트'에서 종목이 빠진다.
리서치의 이벤트는 마크다운 글이라 날짜로 뽑을 수 없다. 섹터·ETF 이벤트는
그대로다.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0152_briefing_event_research'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='stockevent',
            name='stock',
        ),
        migrations.RemoveField(
            model_name='info',
            name='key_briefing',
        ),
        migrations.RemoveField(
            model_name='info',
            name='key_briefing_opinion',
        ),
        migrations.RemoveField(
            model_name='info',
            name='key_briefing_updated_at',
        ),
        migrations.DeleteModel(
            name='Schedule',
        ),
        migrations.DeleteModel(
            name='StockEvent',
        ),
    ]
