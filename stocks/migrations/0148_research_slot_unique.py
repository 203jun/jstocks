# -*- coding: utf-8 -*-
"""
한 종목의 한 질문은 리서치 하나.

화면이 프롬프트를 칸으로 놓고 그 칸에 답을 채우는 방식으로 바뀐다.
같은 칸에 두 건이 있으면 어느 것을 보여줄지 정할 수 없다.

로컬 272건에는 중복이 없었지만 저장 API 가 늘 create() 였어서(0148 과 같이
update_or_create 로 바꾼다) 언제든 생길 수 있는 구조였다. 제약을 걸기 전에
남아 있는 중복을 정리한다 — 내용이 있는 것, 그중 최근 것을 남긴다.
"""
from django.db import migrations


def merge_duplicates(apps, schema_editor):
    StockQuestionReport = apps.get_model('stocks', 'StockQuestionReport')

    seen, doomed = {}, []
    for row in StockQuestionReport.objects.all().order_by('stock_id', 'question'):
        key = (row.stock_id, row.question)
        keep = seen.get(key)
        if keep is None:
            seen[key] = row
            continue
        # 내용이 있는 쪽 우선, 같으면 최근에 고친 쪽
        better = (bool(row.report), row.updated_at) > (bool(keep.report), keep.updated_at)
        if better:
            seen[key] = row
            doomed.append(keep.id)
        else:
            doomed.append(row.id)

    if doomed:
        print()
        print(f'  같은 (종목, 질문) 리서치 {len(doomed)}건을 정리했습니다 '
              f'(내용 있는 최신 것만 남김).')
        StockQuestionReport.objects.filter(id__in=doomed).delete()


def undo(apps, schema_editor):
    """지운 중복은 되살릴 수 없다. 제약만 풀린다."""


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0147_business_report_pipeline_rnd'),
    ]

    operations = [
        migrations.RunPython(merge_duplicates, undo),
        migrations.AlterUniqueTogether(
            name='stockquestionreport',
            unique_together={('stock', 'question')},
        ),
    ]
