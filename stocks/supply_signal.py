# -*- coding: utf-8 -*-
"""
수급 대시보드의 색 기준.

임계값을 템플릿에 박아두면 설명과 화면이 따로 논다. 실제로 한 번 어긋났다 —
설명에는 "±2를 넘으면 주목"이라 적어놓고 화면은 ±1에서 칠하고 있었다.
숫자는 여기 한 곳에 두고 화면과 ⓘ 설명이 같이 읽는다.

경계값은 관심종목의 모든 날(2,985건)에서 잡았다. 하루치로 잡으면 그날이
조용한 날이었는지 아닌지에 따라 값이 흔들린다.
"""

# 60일 지분율 변화. 이 %를 넘으면 색이 붙는다.
# 관측: |값| ≥ 5% 인 날이 외국인 10.5%, 기관 10.1% — 열에 한 번꼴이다.
FLOW_STRONG = 5

# 최근 흐름을 볼 창. 60일과 견줘 방향이 엇갈리면 표식이 붙는다.
FLOW_SHORT_DAYS = 20
FLOW_LONG_DAYS = 60

# 공매도 강도. 이 Z 를 넘으면 색이 붙는다.
# 관측: |Z| ≥ 2 인 날이 8.8% — 열흘에 하루꼴이다. (±1 이면 30% 였다)
SHORT_Z_STRONG = 2


def flow_band(pct):
    """60일 지분율 변화 -> 색 클래스. 20일에는 쓰지 않는다."""
    if pct is None:
        return ''
    if pct >= FLOW_STRONG:
        return 'text-up'
    if pct <= -FLOW_STRONG:
        return 'text-down'
    return ''


def short_z_band(z):
    """
    공매도 강도 -> 색 클래스.

    공매도가 줄면(음수) 빨강이다. 걸어둔 쪽이 물러났다는 뜻이라 주가에는
    좋은 소식이다. 부호와 색이 반대로 보이지만 뜻은 맞다.
    """
    if z is None:
        return ''
    if z <= -SHORT_Z_STRONG:
        return 'text-up'
    if z >= SHORT_Z_STRONG:
        return 'text-down'
    return ''


def turn(long_pct, short_pct):
    """
    긴 흐름과 최근 흐름이 엇갈릴 때만 이름을 붙인다.

    한 기간만 보면 안 보이는 신호다. 60일만 보면 '아직 파는 중'으로 읽고
    지나친다. 관측상 네 번에 한 번쯤 나온다.
    """
    if long_pct is None or short_pct is None:
        return ''
    if long_pct <= 0 < short_pct:
        return '도는 중'
    if short_pct <= 0 < long_pct:
        return '식는 중'
    return ''
