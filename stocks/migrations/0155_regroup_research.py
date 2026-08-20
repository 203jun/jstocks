# -*- coding: utf-8 -*-
"""
리서치 그룹을 세 갈래로 다시 나눈다.

    기업분석  회사가 무엇을 하는 곳인가. 분기보고서로 본다. 잘 안 바뀐다.
    상황추적  지금 무슨 일이 있나. 실적·업황·이벤트. 자주 바뀐다.
    투자판단  그래서 살까 말까. 앞의 둘을 재료로 쓴다.

'업데이트'는 상황추적으로 이름만 바뀌고, 비어 있던 '정리'가 투자판단이
된다. 갈래가 '무엇을 묻는가'가 아니라 '언제 다시 하는가'로 서 있었던 것을
바로잡는 것이라, 이름만 바꿔서는 안 되고 칸을 옮겨야 한다.

    이벤트                    기업분석 -> 상황추적
    핵심브리핑                기업분석 -> 투자판단
    밸류확인·매매근거·
    매매대응·트래커·리스크     업데이트 -> 투자판단

저장된 리서치는 질문 이름으로 붙어 있어 그대로 따라온다. 옮기는 것은
프롬프트 행뿐이다.

모델 이름(QuickReport·SummaryReport)은 그룹 이름과 어긋나게 됐다. 바꾸려면
db_table·API 주소·설정 화면 id 가 다 따라가야 해서 그대로 뒀다.
그룹 이름은 research_slots.GROUP_SPECS 가 정한다.
"""
from django.db import migrations

# 옮길 것. (질문 이름, 원래 모델, 갈 모델)
# 이름이 상용·로컬에서 갈린 것은 둘 다 적는다.
MOVES = [
    ('이벤트', 'ResearchPrompt', 'QuickReport'),
    ('향후 이벤트', 'ResearchPrompt', 'QuickReport'),
    ('핵심브리핑', 'ResearchPrompt', 'SummaryReport'),
    ('밸류에이션', 'ResearchPrompt', 'SummaryReport'),
    ('밸류확인', 'QuickReport', 'SummaryReport'),
    ('매매근거', 'QuickReport', 'SummaryReport'),
    ('매매대응', 'QuickReport', 'SummaryReport'),
    ('트래커', 'QuickReport', 'SummaryReport'),
    ('리스크', 'QuickReport', 'SummaryReport'),
]

COPY_FIELDS = ('question', 'prompt', 'order', 'needs_attachment')


def apply(apps, schema_editor):
    moved, missing = [], []
    for question, src_name, dst_name in MOVES:
        Src = apps.get_model('stocks', src_name)
        Dst = apps.get_model('stocks', dst_name)
        row = Src.objects.filter(question=question).first()
        if not row:
            missing.append(question)
            continue
        if Dst.objects.filter(question=question).exists():
            moved.append(f'{question}: 이미 옮겨져 있음')
            row.delete()
            continue
        Dst.objects.create(**{f: getattr(row, f) for f in COPY_FIELDS})
        row.delete()
        moved.append(f'{question}: {src_name} -> {dst_name}')

    print()
    print(f'  프롬프트 {len(moved)}개를 옮겼습니다.')
    for line in moved:
        print(f'    ✓ {line}')
    if missing:
        print(f'    · 없어서 넘어감: {" · ".join(missing)}')


def undo(apps, schema_editor):
    for question, src_name, dst_name in MOVES:
        Src = apps.get_model('stocks', src_name)
        Dst = apps.get_model('stocks', dst_name)
        row = Dst.objects.filter(question=question).first()
        if row and not Src.objects.filter(question=question).exists():
            Src.objects.create(**{f: getattr(row, f) for f in COPY_FIELDS})
            row.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0154_drop_waiting_report'),
    ]

    operations = [
        migrations.RunPython(apply, undo),
    ]
