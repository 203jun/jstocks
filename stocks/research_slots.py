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

# (이름, 모델, 고치는 API). 화면에 나오는 순서이자 리서치를 쌓는 순서다.
#
#   기업분석  회사가 무엇을 하는 곳인가. 분기보고서로 본다. 잘 안 바뀐다.
#   상황추적  지금 무슨 일이 있나. 실적·업황·이벤트. 자주 바뀐다.
#   투자판단  그래서 살까 말까. 앞의 둘을 재료로 쓴다.
#
# 모델 이름(QuickReport·SummaryReport)은 옛 이름이라 그룹 이름과 어긋난다.
# 이름을 바꾸려면 db_table·API 주소·설정 화면 id 가 다 따라가야 해서
# 그대로 뒀다. 그룹 이름은 여기 이 표가 정한다.
#
# 프롬프트를 고치러 설정 화면까지 갈 이유가 없어서 그 자리에서 고친다.
# 설정 메뉴는 없앨 예정이다.
GROUP_SPECS = [
    ('기업분석', 'ResearchPrompt', 'research-prompt', 'research-common-label'),
    ('상황추적', 'QuickReport', 'quick-report', 'research-update-label'),
    ('투자판단', 'SummaryReport', 'summary-report', 'research-judge-label'),
]

# 한 칸도 안 채운 그룹은 접는다.
#
# 관심종목 1,576개 중 리서치를 시작한 것은 28개다. 접지 않으면 나머지
# 1,548개 종목에서 빈 칸 스물몇 개가 화면을 채운다. 하나라도 채운 그룹은
# 편다 — 시작한 이상 남은 칸이 보여야 한다.


# ── 새 정기보고서가 나왔는지 ────────────────────────────────────────
#
# 사업보고서를 읽고 쓰는 리서치(📄 붙은 칸)는 그 보고서가 새로 나오면 낡는다.
# 관측한 정기보고서 간격은 중앙 119일 — 분기마다 한 번이다.
#
# 달력으로는 못 맞춘다. 사업보고서 47건의 접수일이 3/10~4/6 에 흩어져 있고,
# 결산월도 12월 51 · 9월 40 · 6월 20 · 3월 8 로 제각각이다. 종목마다 그
# 종목의 공시에서 최신 정기보고서를 집어 견준다.

# 공시가 이만큼 안 들어오면 판단을 멈춘다.
#
# 이 신호는 '공시가 들어오고 있다'를 깔고 있다. 수집이 멈추면 새 보고서가
# 나와도 DB 에 없어서 신호가 안 뜨는데, 화면에서는 '갱신할 것 없음'과
# 구별이 안 된다. 아무 말도 안 하는 것이 곧 '괜찮다'로 읽히는 셈이라
# 제일 나쁜 실패다. 그래서 못 믿을 때는 그렇다고 먼저 말한다.
#
# 관심종목 47개를 재보니 마지막 공시까지 중앙 7일, 90%가 21일, 최대 26일이다.
# 45일이면 정상일 때는 뜨지 않고, 수집이 2주 넘게 멈추면 뜬다.
GONGSI_STALE_DAYS = 45

REGULAR_RE = r'(사업보고서|반기보고서|분기보고서)'


def _tidy(text):
    import re
    return re.sub(r'\s+', ' ', text or '').strip()


def gongsi_health(stock, today=None):
    """
    이 종목의 공시를 믿어도 되는지. 믿을 만하면 None.

    'none' 은 수집 대상이 아니라는 뜻이다 — 공시는 관심등급(interest_level)이
    있는 종목만 받는다(daily_update.sh 의 --code fav). 등급을 빼면 리서치는
    남아 있는데 공시가 안 들어온다.
    """
    from django.utils import timezone

    from .models import Gongsi

    today = today or timezone.localdate()
    last = Gongsi.objects.filter(stock=stock).order_by('-date').values_list('date', flat=True).first()
    if last is None:
        return {'state': 'none', 'last': None, 'days': None,
                'text': '이 종목은 공시를 받고 있지 않습니다 — 관심등급을 설정하세요'}
    days = (today - last).days
    if days > GONGSI_STALE_DAYS:
        return {'state': 'stale', 'last': last, 'days': days,
                'text': f'공시가 {last:%y.%m.%d} 에서 멈춰 있습니다({days}일) '
                        f'— 새 보고서가 나왔는지 판단할 수 없습니다'}
    return None


def latest_regular(stock):
    """그 종목의 최신 정기보고서. 달력이 아니라 이 종목의 공시에서 집는다."""
    from .models import Gongsi

    return (Gongsi.objects.filter(stock=stock, title__regex=REGULAR_RE)
            .order_by('-date').first())


def _slot(prompt, report, api, newest=None, trusted=True):
    auto = '{사업보고서' in (prompt.prompt or '')
    # 리서치를 저장한 뒤에 나온 보고서라야 '못 쓴 것'이다. 같은 날이면 그
    # 보고서를 넣고 돌린 것이므로 셈에서 뺀다.
    behind = bool(
        auto and trusted and report is not None and newest is not None
        and newest.date > report.updated_at.date()
    )
    return {
        'question': prompt.question,
        'prompt': prompt.prompt or '',
        'api': api,
        # 사업보고서가 저절로 들어가는 프롬프트인지 (화면의 📄)
        'auto_report': auto,
        'needs_attachment': prompt.needs_attachment,
        'report': report,
        'filled': report is not None,
        'behind': behind,
        'new_report': _tidy(newest.title) if behind else '',
        'new_report_date': newest.date if behind else None,
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

    # 종목마다 한 번이면 되는 것들. 칸마다 물으면 스무 번씩 조회한다.
    health = gongsi_health(stock)
    newest = latest_regular(stock) if health is None else None

    groups, used = [], set()
    for name, model_name, api, label_class in GROUP_SPECS:
        model = apps.get_model('stocks', model_name)
        prompts = list(model.objects.all())
        if not prompts:
            continue
        slots = []
        for p in prompts:
            report = by_question.get(p.question)
            if report is not None:
                used.add(p.question)
            slots.append(_slot(p, report, api, newest, health is None))
        filled = sum(1 for s in slots if s['filled'])
        groups.append({
            'name': name,
            'api': api,
            'label_class': label_class,
            'slots': slots,
            'filled': filled,
            'total': len(slots),
            'behind': sum(1 for s in slots if s['behind']),
            'open': filled > 0,
        })

    custom = sorted(
        (r for q, r in by_question.items() if q not in used),
        key=lambda r: -r.updated_at.timestamp(),
    )
    return groups, custom, health


def slot_alert(stock, report, own_prompt):
    """
    리서치 한 칸의 알림. 없으면 None.

    사업보고서를 쓰는 칸(📄)에만 붙는다. 경쟁사·중장기전망처럼 검색으로만
    쓰는 프롬프트는 정기보고서가 나오든 말든 상관이 없다.
    """
    if not own_prompt or not own_prompt.get('auto_report'):
        return None
    health = gongsi_health(stock)
    if health:
        return health
    if report is None or report.pk is None:
        return None
    newest = latest_regular(stock)
    if newest is None or newest.date <= report.updated_at.date():
        return None
    return {
        'state': 'behind',
        'last': newest.date,
        'text': f'{_tidy(newest.title)} 가 {newest.date:%y.%m.%d} 에 나왔습니다 '
                f'— 이 리서치는 그 전({report.updated_at:%y.%m.%d}) 것입니다',
    }


def find_prompt(question):
    """질문 이름으로 프롬프트 하나. 없으면 None (직접 만든 질문)."""
    from django.apps import apps

    for name, model_name, api, _ in GROUP_SPECS:
        model = apps.get_model('stocks', model_name)
        match = model.objects.filter(question=question).first()
        if match:
            return {
                'group': name,
                'id': match.id,
                'question': match.question,
                'prompt': match.prompt or '',
                # 이 프롬프트를 고치는 곳. /api/<api>/<id>/update/
                'api': api,
                'auto_report': '{사업보고서' in (match.prompt or ''),
                'needs_attachment': match.needs_attachment,
            }
    return None
