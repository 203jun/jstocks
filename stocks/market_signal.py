# -*- coding: utf-8 -*-
"""
시장 지표 해석 — 종합 신호 / 지표 카드 / 상태 변화 로그

MarketIndicator 에 저장된 4개 값을 "지금 사도 되는 자리인가" 관점으로 읽는다.
색은 값의 등락이 아니라 매수 관점의 신호로 준다.

    warn(빨강)    사기 나쁜 신호 — 과열, 순매도, 약세
    ok(초록)      사기 좋은 신호 — 순매수, 강세
    chance(파랑)  기회 구간      — 이격도 침체, ADR 바닥권
    neutral(회색) 중립

지표마다 성격이 다르다. 이격도·ADR 은 높을수록 나쁘고(과열), 수급·200일선은
높을수록 좋다. 그래서 "값이 올랐는가"로 색을 칠하면 안 된다.

200일선은 종합 점수에 더하지 않고 브레이크로 쓴다. 합산에 넣으면 약세장일 때
점수가 내려가 "기회"로 밀려나는데, 200일선의 역할은 정확히 그 반대다.
"""
from decimal import Decimal

from .models import MarketIndicator

# 이격도 임계값은 시장별로 다르다 (코스닥이 더 크게 흔들린다)
DISPARITY_THRESHOLDS = {
    'KOSPI': (Decimal('95'), Decimal('105')),
    'KOSDAQ': (Decimal('93'), Decimal('107')),
}
ADR_THRESHOLDS = (Decimal('75'), Decimal('120'))

# 임계선 근처에서 값이 넘나들면 상태 변화가 5일에 한 번씩 생겨 로그가 노이즈로
# 가득 찬다. 새 상태가 이만큼 유지돼야 '변화'로 인정한다 (104건 -> 44건).
EVENT_MIN_DAYS = 3

# 상태 변화 로그와 지속 일수를 계산할 범위. 늘어나도 조회가 무거워지지 않게 자른다.
HISTORY_LIMIT = 750

# save_market_indicator 와 같은 값. 백분위 표본이 몇 일인지 화면에 밝히는 데 쓴다.
PERCENTILE_WINDOW = 250

# 신중한 쪽 -> 낙관적인 쪽 순서. 브레이크는 이 배열에서 한 칸 앞으로 당긴다.
SIGNAL_LEVELS = [
    ('hot', '🔴', '과열', '지금 사고 싶은 종목, 2주 뒤에도 살 수 있습니다'),
    ('warn', '🟠', '주의', '살 거면 반만. 나머지는 열흘 뒤의 나에게 맡기세요'),
    ('neutral', '⚪', '중립', '시장은 핑계가 안 됩니다. 종목만 보세요'),
    ('watch', '🟢', '관심', '평소 담고 싶던 자리입니다. 서두르지만 마세요'),
    ('cold', '🔵', '침체', '무섭게 느껴진다면 대체로 맞는 자리입니다'),
]
BEAR_NOTE = '다만 200일선 아래입니다 — 눌림목이 아니라 하락 중간일 수 있습니다'

EVENT_TEXT = {
    ('disparity', 'mid', 'hot'): '이격도 과열권 진입',
    ('disparity', 'hot', 'mid'): '이격도 과열 해소',
    ('disparity', 'mid', 'cold'): '이격도 침체권 진입',
    ('disparity', 'cold', 'mid'): '이격도 침체 벗어남',
    ('disparity', 'hot', 'cold'): '이격도 과열에서 침체로',
    ('disparity', 'cold', 'hot'): '이격도 침체에서 과열로',
    ('adr', 'mid', 'hot'): 'ADR 과열권 진입',
    ('adr', 'hot', 'mid'): 'ADR 과열 해소',
    ('adr', 'mid', 'cold'): 'ADR 바닥권 진입',
    ('adr', 'cold', 'mid'): 'ADR 바닥권 벗어남',
    ('adr', 'hot', 'cold'): 'ADR 과열에서 바닥권으로',
    ('adr', 'cold', 'hot'): 'ADR 바닥권에서 과열로',
    ('foreign', 'minus', 'plus'): '외국인 순매수 전환',
    ('foreign', 'plus', 'minus'): '외국인 순매도 전환',
    ('ma200', 'minus', 'plus'): '200일선 상향 돌파',
    ('ma200', 'plus', 'minus'): '200일선 하향 이탈',
}


# --------------------------------------------------------------------- #
# 상태 판정
# --------------------------------------------------------------------- #

def _band_state(value, low, high):
    if value is None:
        return None
    return 'hot' if value >= high else ('cold' if value <= low else 'mid')


def _sign_state(value):
    if value is None:
        return None
    return 'plus' if value > 0 else ('minus' if value < 0 else 'zero')


def _confirm_events(series, min_days):
    """
    (date, state) 시퀀스에서 min_days 이상 유지된 상태 변화만 뽑는다.
    반환은 (전환일, 이전상태, 새상태) 목록.
    """
    events = []
    confirmed = pending = pending_from = None
    count = 0
    for date, state in series:
        if state is None:
            continue
        if confirmed is None:
            confirmed = state
            continue
        if state == confirmed:
            pending, count = None, 0
            continue
        if state == pending:
            count += 1
        else:
            pending, pending_from, count = state, date, 1
        if count >= min_days:
            events.append((pending_from, confirmed, state))
            confirmed, pending, count = state, None, 0
    return events


def _streak(series):
    """오늘 상태가 며칠째인지. (상태, 일수, 조회범위에 걸렸는지)"""
    values = [(d, s) for d, s in series if s is not None]
    if not values:
        return None, 0, False
    current = values[-1][1]
    days = 0
    for _, state in reversed(values):
        if state != current:
            break
        days += 1
    return current, days, days == len(values)


# --------------------------------------------------------------------- #
# 게이지
# --------------------------------------------------------------------- #

def _pos(value, low, high):
    if high == low:
        return 50.0
    ratio = (Decimal(value) - Decimal(low)) / (Decimal(high) - Decimal(low)) * 100
    return round(min(100.0, max(0.0, float(ratio))), 2)


def _banded_gauge(value, low, high):
    """
    임계값 2개짜리 게이지 (이격도, ADR).
    low/high 가 늘 1/3, 2/3 지점에 오도록 축을 잡아 두 게이지의 읽는 법을 통일한다.
    """
    width = high - low
    return {
        'pos': _pos(value, low - width, high + width),
        'marks': [{'pos': 33.33, 'label': f'{low:g}'}, {'pos': 66.67, 'label': f'{high:g}'}],
        'zones': 'band',
    }


def _zero_gauge(value, span):
    """임계값이 0 하나뿐인 게이지 (수급, 200일선). 0이 정중앙."""
    span = abs(span) or 1
    return {
        'pos': _pos(value, -span, span),
        'marks': [{'pos': 50.0, 'label': '0'}],
        'zones': 'zero',
    }


def _fmt_eok(value_in_million):
    """백만원 -> 억/조 표기"""
    eok = Decimal(value_in_million) / 100
    if abs(eok) >= 10000:
        return f'{eok / 10000:+,.2f}조'
    return f'{eok:+,.0f}억'


# --------------------------------------------------------------------- #
# 조립
# --------------------------------------------------------------------- #

def build_market_panel(market):
    """
    화면에 그대로 뿌릴 수 있는 종합 신호 + 지표 카드 + 상태 변화 로그.
    데이터가 없으면 None.
    """
    rows = list(
        MarketIndicator.objects.filter(market=market)
        .order_by('-date')
        .values_list(
            'date', 'disparity', 'adr', 'foreign_net_20d', 'ma200_gap',
            'foreign_net_20d_pct', 'ma200_gap_pct',
        )[:HISTORY_LIMIT]
    )
    if not rows:
        return None
    rows.reverse()  # 오래된 것부터

    dis_low, dis_high = DISPARITY_THRESHOLDS.get(market, DISPARITY_THRESHOLDS['KOSPI'])
    adr_low, adr_high = ADR_THRESHOLDS

    series = {
        'disparity': [(r[0], _band_state(r[1], dis_low, dis_high)) for r in rows],
        'adr': [(r[0], _band_state(r[2], adr_low, adr_high)) for r in rows],
        'foreign': [(r[0], _sign_state(r[3])) for r in rows],
        'ma200': [(r[0], _sign_state(r[4])) for r in rows],
    }
    streaks = {key: _streak(seq) for key, seq in series.items()}

    date, disparity, adr, foreign, gap, foreign_pct, gap_pct = rows[-1]
    # 게이지 폭은 조회 범위 안의 실제 최대치에서 잡는다.
    # 코스피와 코스닥의 수급 규모가 10배 넘게 차이나 공통 눈금을 쓸 수 없다.
    foreign_span = max((abs(r[3]) for r in rows if r[3] is not None), default=0)
    gap_span = max((abs(r[4]) for r in rows if r[4] is not None), default=0)

    # 백분위를 낸 표본 크기. 창(250일)이 꽉 차기 전에는 값이 흔들리므로 화면에 밝힌다.
    samples = {
        'foreign': min(sum(1 for r in rows if r[3] is not None), PERCENTILE_WINDOW),
        'ma200': min(sum(1 for r in rows if r[4] is not None), PERCENTILE_WINDOW),
    }

    cards = _build_cards(
        disparity, adr, foreign, gap, foreign_pct, gap_pct,
        (dis_low, dis_high), (adr_low, adr_high),
        foreign_span, gap_span, streaks, samples,
    )
    if not cards:
        return None

    return {
        'date': date,
        'signal': _build_signal(streaks, series),
        'cards': cards,
        'events': _build_events(series, date),
        'samples': samples,
    }


def _card(label, value, delta, state, badge, streak, gauge):
    return {
        'label': label, 'value': value, 'delta': delta,
        'state': state, 'badge': badge, 'streak': streak, **gauge,
    }


def _streak_text(streaks, key):
    _, days, capped = streaks[key]
    if not days:
        return ''
    return f'{days}일+' if capped else f'{days}일째'


def _percentile_text(pct, sample):
    """
    백분위 표기. 창이 꽉 차기 전에는 값이 흔들리므로 표본 수를 함께 적는다.
    (창이 꽉 찬 뒤에는 늘 250이라 굳이 반복하지 않는다)
    """
    if pct is None:
        return ''
    text = f'백분위 {pct:.0f}%'
    if sample < PERCENTILE_WINDOW:
        text += f' · 표본 {sample}일'
    return text


def _build_cards(disparity, adr, foreign, gap, foreign_pct, gap_pct,
                 dis_th, adr_th, foreign_span, gap_span, streaks, samples):
    cards = []

    if disparity is not None:
        low, high = dis_th
        state, badge = (('warn', '과열') if disparity >= high else
                        ('chance', '침체') if disparity <= low else ('neutral', '중립'))
        cards.append(_card('이격도', f'{disparity:,.2f}', '', state, badge,
                           _streak_text(streaks, 'disparity'),
                           _banded_gauge(disparity, low, high)))

    if adr is not None:
        low, high = adr_th
        state, badge = (('warn', '과열') if adr >= high else
                        ('chance', '바닥권') if adr <= low else ('neutral', '중립'))
        cards.append(_card('ADR', f'{adr:,.2f}', '', state, badge,
                           _streak_text(streaks, 'adr'),
                           _banded_gauge(adr, low, high)))

    if foreign is not None:
        state, badge = (('ok', '순매수') if foreign > 0 else
                        ('warn', '순매도') if foreign < 0 else ('neutral', '중립'))
        cards.append(_card('외인 20일', _fmt_eok(foreign),
                           _percentile_text(foreign_pct, samples['foreign']),
                           state, badge,
                           _streak_text(streaks, 'foreign'),
                           _zero_gauge(foreign, foreign_span)))

    if gap is not None:
        state, badge = (('ok', '강세') if gap > 0 else
                        ('warn', '약세') if gap < 0 else ('neutral', '중립'))
        # 200일선은 판정하지 않고 값과 백분위만 보여준다. 추세 시계열이라
        # 상승장에서는 백분위가 계속 상단에 붙어 있어(관측 75~78%) 과열 판정에
        # 쓰면 양치기가 된다. 배지는 강세/약세 레짐만 표시한다.
        cards.append(_card('200일선', f'{gap:+,.2f}%',
                           _percentile_text(gap_pct, samples['ma200']),
                           state, badge,
                           _streak_text(streaks, 'ma200'),
                           _zero_gauge(gap, gap_span)))

    return cards


def _build_signal(streaks, series):
    """
    참을 이유 점수(-3 ~ +3)로 5단계를 정한다. 높을수록 참아야 한다.
    200일선은 점수에 넣지 않고, 아래면 판정을 한 칸 신중한 쪽으로 당긴다.
    """
    dis_state = streaks['disparity'][0]
    adr_state = streaks['adr'][0]
    foreign_state = streaks['foreign'][0]
    ma200_state = streaks['ma200'][0]

    if dis_state is None or adr_state is None or foreign_state is None:
        return None

    score = 0
    score += 1 if dis_state == 'hot' else (-1 if dis_state == 'cold' else 0)
    score += 1 if adr_state == 'hot' else (-1 if adr_state == 'cold' else 0)
    score += -1 if foreign_state == 'plus' else (1 if foreign_state == 'minus' else 0)

    index = 0 if score >= 2 else (1 if score == 1 else (2 if score == 0 else (3 if score == -1 else 4)))
    braked = ma200_state == 'minus'
    if braked:
        index = max(0, index - 1)

    key, emoji, name, message = SIGNAL_LEVELS[index]

    # 근거 한 줄 — 중립이 아닌 지표만 지속 일수와 함께
    reasons = []
    for field, label, texts in (
        ('disparity', '이격도', {'hot': '과열', 'cold': '침체'}),
        ('adr', 'ADR', {'hot': '과열', 'cold': '바닥권'}),
        ('foreign', '외국인', {'plus': '순매수', 'minus': '순매도'}),
    ):
        text = texts.get(streaks[field][0])
        if text:
            reasons.append(f'{label} {text} {_streak_text(streaks, field)}'.strip())

    return {
        'key': key, 'emoji': emoji, 'name': name, 'message': message,
        'score': score, 'braked': braked,
        'bear_note': BEAR_NOTE if braked else '',
        'reason': ' · '.join(reasons),
    }


def _build_events(series, today, limit=5):
    """확정된 상태 변화를 최근 순으로. limit 개."""
    events = []
    for field, seq in series.items():
        for date, before, after in _confirm_events(seq, EVENT_MIN_DAYS):
            text = EVENT_TEXT.get((field, before, after))
            if text:
                events.append({'date': date, 'text': text, 'ago': (today - date).days})
    events.sort(key=lambda e: e['date'], reverse=True)
    return events[:limit]
