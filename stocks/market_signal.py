# -*- coding: utf-8 -*-
"""
시장 지표 상태 판정 + 화면 표시용 카드 구성

MarketIndicator 에 저장된 4개 값을 "지금 사도 되는 자리인가" 관점으로 해석한다.
색은 값의 등락이 아니라 매수 관점의 신호로 준다.

    warn(빨강)   사기 나쁜 신호 — 과열, 순매도, 약세
    ok(초록)     사기 좋은 신호 — 순매수, 강세
    chance(파랑) 기회 구간      — 이격도 침체, ADR 바닥권
    neutral(회색) 중립

지표마다 성격이 다르다는 점에 주의한다. 이격도·ADR 은 높을수록 나쁘고(과열),
수급·200일선은 높을수록 좋다. 그래서 "값이 올랐는가"로 색을 칠하면 안 된다.

임계값은 종합 신호(다음 단계)에서도 그대로 쓰므로 여기에 모아 둔다.
"""
from decimal import Decimal

from django.db.models import Max, Min

from .models import MarketIndicator

# 이격도 임계값은 시장별로 다르다 (코스닥이 더 크게 흔들린다)
DISPARITY_THRESHOLDS = {
    'KOSPI': (Decimal('95'), Decimal('105')),
    'KOSDAQ': (Decimal('93'), Decimal('107')),
}
ADR_THRESHOLDS = (Decimal('75'), Decimal('120'))


def _pos(value, low, high):
    """value 를 [low, high] 구간 안의 0~100 위치로. 범위를 벗어나면 끝에 붙인다."""
    if high == low:
        return 50.0
    ratio = (Decimal(value) - Decimal(low)) / (Decimal(high) - Decimal(low)) * 100
    return round(min(100.0, max(0.0, float(ratio))), 2)


def _banded_gauge(value, low, high):
    """
    임계값 2개짜리 게이지 (이격도, ADR).

    low/high 가 항상 1/3, 2/3 지점에 오도록 축을 잡는다. 두 게이지의 읽는 법이
    같아져서 "오른쪽 칸에 있으면 과열"이 눈에 익는다.
    """
    width = high - low
    axis_low, axis_high = low - width, high + width
    return {
        'pos': _pos(value, axis_low, axis_high),
        'marks': [
            {'pos': 33.33, 'label': f'{low:g}'},
            {'pos': 66.67, 'label': f'{high:g}'},
        ],
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


def _card(label, value_text, delta_text, state, badge, gauge):
    return {
        'label': label,
        'value': value_text,
        'delta': delta_text,
        'state': state,
        'badge': badge,
        **gauge,
    }


def build_indicator_cards(market):
    """
    화면에 그대로 뿌릴 수 있는 지표 카드 4개를 만든다.
    데이터가 없으면 None, 개별 지표가 비어 있으면 그 카드만 뺀다.
    """
    rows = list(MarketIndicator.objects.filter(market=market).order_by('-date')[:2])
    if not rows:
        return None
    cur = rows[0]
    prev = rows[1] if len(rows) > 1 else None

    # 수급·200일선 게이지 폭은 시장별 실제 최대치에서 잡는다.
    # 코스피와 코스닥의 수급 규모가 10배 넘게 차이나 공통 눈금을 쓸 수 없다.
    span = MarketIndicator.objects.filter(market=market).aggregate(
        f_max=Max('foreign_net_20d'), f_min=Min('foreign_net_20d'),
        g_max=Max('ma200_gap'), g_min=Min('ma200_gap'),
    )
    foreign_span = max(abs(span['f_max'] or 0), abs(span['f_min'] or 0))
    gap_span = max(abs(span['g_max'] or 0), abs(span['g_min'] or 0))

    def delta(field, fmt):
        if prev is None:
            return ''
        now, before = getattr(cur, field), getattr(prev, field)
        if now is None or before is None:
            return ''
        diff = now - before
        arrow = '▲' if diff > 0 else ('▼' if diff < 0 else '–')
        return f'{arrow} {fmt(abs(diff))}'

    cards = []

    # 1. 이격도 — 높을수록 과열
    if cur.disparity is not None:
        low, high = DISPARITY_THRESHOLDS.get(market, DISPARITY_THRESHOLDS['KOSPI'])
        if cur.disparity >= high:
            state, badge = 'warn', '과열'
        elif cur.disparity <= low:
            state, badge = 'chance', '침체'
        else:
            state, badge = 'neutral', '중립'
        cards.append(_card(
            '이격도', f'{cur.disparity:,.2f}',
            delta('disparity', lambda v: f'{v:,.2f}'),
            state, badge, _banded_gauge(cur.disparity, low, high),
        ))

    # 2. ADR — 높을수록 과열
    if cur.adr is not None:
        low, high = ADR_THRESHOLDS
        if cur.adr >= high:
            state, badge = 'warn', '과열'
        elif cur.adr <= low:
            state, badge = 'chance', '바닥권'
        else:
            state, badge = 'neutral', '중립'
        cards.append(_card(
            'ADR', f'{cur.adr:,.2f}',
            delta('adr', lambda v: f'{v:,.2f}'),
            state, badge, _banded_gauge(cur.adr, low, high),
        ))

    # 3. 외국인 20일 누적 순매수 — 부호가 곧 방향
    if cur.foreign_net_20d is not None:
        if cur.foreign_net_20d > 0:
            state, badge = 'ok', '순매수'
        elif cur.foreign_net_20d < 0:
            state, badge = 'warn', '순매도'
        else:
            state, badge = 'neutral', '중립'
        cards.append(_card(
            '외인 20일', _fmt_eok(cur.foreign_net_20d),
            delta('foreign_net_20d', lambda v: _fmt_eok(v).lstrip('+')),
            state, badge, _zero_gauge(cur.foreign_net_20d, foreign_span),
        ))

    # 4. 200일선 대비 — 위면 강세 레짐
    if cur.ma200_gap is not None:
        if cur.ma200_gap > 0:
            state, badge = 'ok', '강세'
        elif cur.ma200_gap < 0:
            state, badge = 'warn', '약세'
        else:
            state, badge = 'neutral', '중립'
        cards.append(_card(
            '200일선', f'{cur.ma200_gap:+,.2f}%',
            delta('ma200_gap', lambda v: f'{v:,.2f}%p'),
            state, badge, _zero_gauge(cur.ma200_gap, gap_span),
        ))

    if not cards:
        return None
    return {'date': cur.date, 'cards': cards}
