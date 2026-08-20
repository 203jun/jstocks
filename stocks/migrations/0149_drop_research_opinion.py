# -*- coding: utf-8 -*-
"""
리서치의 '요약' 칸을 없앤다.

리포트를 다시 짧게 줄여 적는 칸이었다. 272건 중 4건만 채워졌고 그 4건도
전부 2026년 4월, 한 종목에 몰려 있다(3자짜리 시험 흔적 포함).

지금 프롬프트들은 출력 형식에 '## 요약 (5~7줄)' 을 넣어 두고 있다.
AI 답변 맨 앞에 이미 요약이 들어 있으니 그것을 또 요약할 이유가 없다.
지우는 내용도 리포트에서 뽑아낸 파생물이라 원본이 그대로 남는다.

섹터 리서치의 같은 칸도 같이 없앤다 — 화면 어디에서도 쓰지 않았고 0건이다.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0148_research_slot_unique'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='sectorquestionreport',
            name='my_opinion',
        ),
        migrations.RemoveField(
            model_name='stockquestionreport',
            name='my_opinion',
        ),
    ]
