# -*- coding: utf-8 -*-
"""
차트에서 읽어내는 신호 — 이평 배열, 눌림목, 수급 연속성, 괴리율.

메인 화면 현황 표가 쓰던 계산이다. 종목 상세에서도 같은 것을 보여주려니
한 벌 더 쓸 뻔했다. 두 화면이 같은 말을 다르게 하면 안 되므로 여기 모은다.

들어오는 일봉은 모두 최신이 앞(내림차순)이다 — 화면 코드가 그렇게 뽑는다.
"""

# 이평선끼리 이만큼은 벌어져야 '배열'로 본다. 붙어 있는 것을 정배열이라
# 부르면 거의 모든 날이 정배열이 된다.
ALIGN_MARGIN = 1.005

# 눌림목 구간. 20일선에서 얼마나 떨어졌는가(%).
PULLBACK_BANDS = [
    (5, '과열'),
    (2, '추세중'),
    (-2, '얕은눌림'),
    (-5, '깊은눌림'),
]
PULLBACK_LAST = '이탈'

# 수급이 이만큼 연달아 들어오면 표시한다. 이틀은 흔하다.
STREAK_MIN = 3
STREAK_WINDOW = 20


def _ma(daily, n, skip=0):
    rows = daily[skip:skip + n]
    return sum(d.closing_price for d in rows) / n if len(rows) == n else None


def ma_alignment(daily):
    """
    'bull' 정배열 · 'bear' 역배열 · 'mixed' 뒤섞임 · '' 데이터 부족.

    120일선의 방향까지 본다. 배열만 맞고 120일선이 내려가고 있으면 아직
    돌아선 것이 아니다.
    """
    if len(daily) < 125:
        return ''
    ma5, ma20 = _ma(daily, 5), _ma(daily, 20)
    ma60, ma120 = _ma(daily, 60), _ma(daily, 120)
    ma120_prev = _ma(daily, 120, skip=5)
    m = ALIGN_MARGIN
    if (ma5 > ma20 * m and ma20 > ma60 * m and ma60 > ma120 * m
            and ma120 > ma120_prev):
        return 'bull'
    if (ma5 * m < ma20 and ma20 * m < ma60 and ma60 * m < ma120
            and ma120 < ma120_prev):
        return 'bear'
    return 'mixed'


def pullback(daily, align):
    """
    (20일선 대비 %, 이름). 정배열일 때만 본다.

    역배열에서 20일선 아래는 눌림목이 아니라 그냥 하락이다.
    """
    if align != 'bull' or len(daily) < 20:
        return None, ''
    ma20 = _ma(daily, 20)
    gap = round((daily[0].closing_price - ma20) / ma20 * 100, 1)
    for edge, name in PULLBACK_BANDS:
        if gap > edge:
            return gap, name
    return gap, PULLBACK_LAST


def _streak(values):
    """오늘이 창 안의 최대면 '20일', 아니면 연속 며칠째인지."""
    if not values:
        return ''
    if values[0] > 0 and values[0] >= max(values):
        return f'{STREAK_WINDOW}일'
    days = 0
    for v in values:
        if v > 0:
            days += 1
        else:
            break
    return str(days) if days >= STREAK_MIN else ''


def investor_streaks(inv_data):
    """(기관, 외국인) 연속 매수 표시. inv_data 는 최신이 앞."""
    if not inv_data:
        return '', ''
    return (_streak([d.institution for d in inv_data]),
            _streak([d.foreign for d in inv_data]))


def report_gap(stock, latest_report=None):
    """최신 목표가 ÷ 현재가 - 100. 목표가가 없으면 None."""
    from .models import Report

    if latest_report is None:
        latest_report = (Report.objects
                         .filter(stock=stock, target_price__isnull=False)
                         .order_by('-date').first())
    if not latest_report or not latest_report.target_price or not stock.current_price:
        return None
    return round((latest_report.target_price / stock.current_price - 1) * 100, 1)


ALIGN_NAMES = {'bull': '정배열', 'bear': '역배열', 'mixed': '뒤섞임'}
