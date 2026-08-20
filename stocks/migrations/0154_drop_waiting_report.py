# -*- coding: utf-8 -*-
"""
리서치의 '대기' 그룹을 없앤다.

QuickReport 를 복사해 만든 것이었다. 커밋 메시지가 "정리리포트와 동일
구조"가 전부고, 모델·뷰·URL·설정 화면 302줄이 글자 하나 안 바뀐 복제였다.

상용에 이름 네 개(옥석가리기·회사스냅샷·매매매력도·매매트래킹)가 등록돼
있지만 그 이름으로 저장된 리서치는 한 건도 없다.

기업분석·업데이트·일반은 '무엇을 묻는가'로 갈린다. 대기는 그 축이 아니라
'어느 단계 종목인가'였다. 그건 프롬프트 그룹이 아니라 종목의 관심등급
(interest_level)이 할 일이다.
"""

from django.db import migrations


def report(apps, schema_editor):
    """지우기 전에 남는 것이 있는지 알린다."""
    WaitingReport = apps.get_model('stocks', 'WaitingReport')
    StockQuestionReport = apps.get_model('stocks', 'StockQuestionReport')

    names = list(WaitingReport.objects.values_list('question', flat=True))
    print()
    if not names:
        print('  대기 프롬프트 없음')
        return
    print(f'  대기 프롬프트 {len(names)}개 삭제: {" · ".join(names)}')
    left = StockQuestionReport.objects.filter(question__in=names).count()
    if left:
        # 저장된 내용은 안 지운다. 갈 칸이 없어져 '일반'으로 내려갈 뿐이다.
        print(f'  (그 이름으로 저장된 리서치 {left}건은 일반으로 내려갑니다)')


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0153_drop_briefing_event'),
    ]

    operations = [
        migrations.RunPython(report, migrations.RunPython.noop),
        migrations.DeleteModel(
            name='WaitingReport',
        ),
    ]
