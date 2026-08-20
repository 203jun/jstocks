# -*- coding: utf-8 -*-
"""
리서치를 '프롬프트 칸(슬롯)'으로 본다.

지금까지는 저장된 리서치만 화면에 늘어놓았다. 그래서 무엇을 안 했는지가
보이지 않았고, 새로 하려면 '+ 추가' 로 빈 리서치를 만든 뒤 프롬프트
스물두 개 중에서 이름을 골라야 했다.

뒤집는다. 등록된 프롬프트가 곧 칸이다. 채워졌으면 진하게 날짜와 함께,
안 채웠으면 흐리게. 칸을 누르면 그 칸의 프롬프트가 복사되고, 답을 받아
붙여넣으면 그 자리에 저장된다.

데이터가 이미 이 모양이었다. 관측 272건에서 같은 (종목, 질문) 이 두 번
나온 적이 없고, 리서치를 시작한 28개 종목이 모두 9~10칸을 채웠다.
칸을 하나씩 골라 채우는 것이 원래 쓰던 방식이다.

프롬프트에 없는 질문(직접 만든 것)은 '일반' 으로 따로 모은다. 프롬프트를
지우면 그 리서치도 여기로 내려온다 — 사라지지 않는다.
"""

# (이름, 모델, 설정 화면 패널). 화면에 나오는 순서다.
GROUP_SPECS = [
    ('기업분석', 'ResearchPrompt', 'research-prompt-panel'),
    ('업데이트', 'QuickReport', 'quick-report-panel'),
    ('정리', 'SummaryReport', 'quick-report-panel'),
    ('대기', 'WaitingReport', 'waiting-report-panel'),
]

# 한 칸도 안 채운 그룹은 접는다.
#
# 관심종목 1,576개 중 리서치를 시작한 것은 28개다. 접지 않으면 나머지
# 1,548개 종목에서 빈 칸 스물몇 개가 화면을 채운다. 하나라도 채운 그룹은
# 편다 — 시작한 이상 남은 칸이 보여야 한다.


def _slot(prompt, report, panel):
    return {
        'question': prompt.question,
        'prompt': prompt.prompt or '',
        'panel': panel,
        # 사업보고서가 저절로 들어가는 프롬프트인지 (화면의 📄)
        'auto_report': '{사업보고서' in (prompt.prompt or ''),
        'needs_attachment': prompt.needs_attachment,
        'report': report,
        'filled': report is not None,
    }


def build_groups(stock, reports=None):
    """
    [{name, panel, slots, filled, total, open}, …] 과 남은 '일반' 리서치.

    reports 를 넘기면 다시 조회하지 않는다 (종목 화면이 이미 갖고 있다).
    """
    from django.apps import apps

    from .models import StockQuestionReport

    if reports is None:
        reports = StockQuestionReport.objects.filter(stock=stock)
    by_question = {}
    for r in reports:
        # 슬롯 하나에 리서치 하나다. 옛 데이터에 중복이 있으면 최근 것을 쓴다.
        old = by_question.get(r.question)
        if old is None or r.updated_at > old.updated_at:
            by_question[r.question] = r

    groups, used = [], set()
    for name, model_name, panel in GROUP_SPECS:
        model = apps.get_model('stocks', model_name)
        prompts = list(model.objects.all())
        if not prompts:
            continue
        slots = []
        for p in prompts:
            report = by_question.get(p.question)
            if report is not None:
                used.add(p.question)
            slots.append(_slot(p, report, panel))
        filled = sum(1 for s in slots if s['filled'])
        groups.append({
            'name': name,
            'panel': panel,
            'slots': slots,
            'filled': filled,
            'total': len(slots),
            'open': filled > 0,
        })

    custom = sorted(
        (r for q, r in by_question.items() if q not in used),
        key=lambda r: (not r.is_tracking, -r.updated_at.timestamp()),
    )
    return groups, custom


def find_prompt(question):
    """질문 이름으로 프롬프트 하나. 없으면 None (직접 만든 질문)."""
    from django.apps import apps

    for name, model_name, panel in GROUP_SPECS:
        model = apps.get_model('stocks', model_name)
        match = model.objects.filter(question=question).first()
        if match:
            return {
                'group': name,
                'question': match.question,
                'prompt': match.prompt or '',
                'panel': panel,
                'auto_report': '{사업보고서' in (match.prompt or ''),
                'needs_attachment': match.needs_attachment,
            }
    return None
