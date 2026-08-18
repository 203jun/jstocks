# -*- coding: utf-8 -*-
"""
애널리스트 리포트에서 신호를 뽑는 규칙.

리포트 표의 괴리율은 '발행일 목표가 ÷ 발행일 종가'라서 한 번 정해지면 변하지
않는다. 오늘 이 종목을 살지 말지를 알려주는 값이 아니라, 그날 애널리스트가
주가 대비 얼마나 위를 봤는지를 적어둔 기록이다. 즉 확신도다.

문제는 그 확신도가 대체로 비슷하다는 것이다. 보유 종목 2,045건을 재보니
중앙값이 +28.4%, 절반이 +21~39% 안에 들어온다. 목표가를 주가보다 30% 남짓
위에 잡는 것이 한국 리포트의 관행이라 그 구간에는 정보가 없다.

그래서 흔한 가운데는 흐리게 두고 드문 양끝만 세운다. 아래 경계값은 그 2,045건의
분포에서 가져왔다.
"""

from datetime import timedelta

# 발행 시점 괴리율의 경계 (%). 괄호 안은 2,045건에서 관측된 비중.
GAP_OVERSHOOT = 0    # 미만 — 발행 시점에 이미 주가가 목표가를 넘어섰다 (1.1%)
GAP_THIN = 10        # 이하 — 애널리스트도 여력을 거의 못 봤다 (4.7%)
GAP_STRONG = 50      # 이상 — 리스크를 지고 세게 지른 콜 (상위 10%)

# 목표가 방향을 세는 창과 문턱
CYCLE_DAYS = 90      # 분기 실적 주기와 맞춘다. 이보다 짧으면 표본이 안 모인다.
CYCLE_MOVE = 1.0     # % — 이보다 작게 움직이면 '유지'로 본다

# 컨센서스에서 혼자 튄 목표가로 볼 기준 (%).
# 같은 창의 목표가 1,096건을 재보니 평균과의 괴리 중앙값이 9.2%,
# 90% 지점이 27.1%였다. 25%면 열에 하나쯤 걸린다.
CONSENSUS_OUTLIER = 25
CONSENSUS_MIN_PROVIDERS = 3   # 증권사가 이보다 적으면 '평균'이라 부를 수 없다


def gap_band(gap):
    """
    발행 시점 괴리율 -> 강조 등급(CSS 클래스명). 값이 없으면 빈 문자열.

    GAP_THIN 이하가 왜 경고인지: 한국은 매도 의견을 사실상 못 낸다. 그래서
    '매수 유지, 목표가 하향'으로 목표가만 주가 근처까지 내리는 것이 돌려 말한
    매도에 가깝다. 의견란은 BUY 인데 괴리율이 한 자리면 그 쪽을 봐야 한다.
    """
    if gap is None:
        return ''
    if gap < GAP_OVERSHOOT:
        return 'gap-over'
    if gap <= GAP_THIN:
        return 'gap-thin'
    if gap >= GAP_STRONG:
        return 'gap-strong'
    return 'gap-plain'


def current_gap_band(gap):
    """
    현재가 기준 괴리율 -> 강조 등급. 아래쪽 경계는 발행 시점과 같지만
    위쪽(GAP_STRONG)은 일부러 세우지 않는다.

    한 리포트 안에서 목표가는 고정이므로, 발행 시점 대비 괴리율이 벌어졌다면
    그건 100% 주가가 빠졌다는 뜻이다. 그걸 빨갛게 칠하면 '많이 떨어진 종목'이
    상승 여력으로 보이게 된다. 목표가는 주가에 후행해서 뒤늦게 내려오는
    경우가 많아 더 그렇다.

    그래서 여기서는 목표가에 다다른 쪽만 세운다. 살지 말지를 묻는 자리에서
    쓸모 있는 경고는 '이미 다 왔다' 뿐이다.
    """
    if gap is None:
        return ''
    if gap < GAP_OVERSHOOT:
        return 'gap-over'
    if gap <= GAP_THIN:
        return 'gap-thin'
    return 'gap-plain'


def build_target_panel(stock, today):
    """
    리포트 탭 맨 위 '목표가' 카드에 들어갈 값들. 리포트가 없으면 None.

    괴리율 숫자만 늘어놓으면 읽어내기가 어렵다. +93%가 세게 지른 콜인지
    주가가 반토막 난 결과인지, 그 증권사만 그런 건지 다들 그런 건지에 따라
    뜻이 정반대다. 그래서 세 가지를 함께 낸다.

      괴리율   목표가와 지금 주가의 간격, 그리고 그게 왜 그 값인지
      컨센     같은 창의 증권사 평균 — 혼자 튄 값인지 가른다
      사이클   목표가가 오르는 중인지 내리는 중인지

    셋을 읽어 한 줄로 정리한 것이 reading 이다.
    """
    from .models import DailyChart, Report

    rows = list(Report.objects
                .filter(stock=stock, target_price__isnull=False, date__isnull=False)
                .order_by('date')
                .values_list('date', 'provider', 'target_price'))
    if not rows:
        return None

    date, provider, target = rows[-1]
    current = stock.current_price or 0
    panel = {
        'target': target, 'date': date, 'provider': provider, 'total': len(rows),
        'gap_now': None, 'gap_band': '', 'gap_issued': None, 'price_move': None,
        'consensus': None, 'providers': 0, 'consensus_gap': None, 'outlier': False,
        'up': 0, 'flat': 0, 'down': 0, 'window': CYCLE_DAYS, 'reading': '',
        'recent_n': 0, 'age': (today - date).days,
    }

    if current:
        panel['gap_now'] = round((target / current - 1) * 100, 1)
        panel['gap_band'] = current_gap_band(panel['gap_now'])
        closing = (DailyChart.objects.filter(stock=stock, date=date)
                   .values_list('closing_price', flat=True).first())
        if closing:
            panel['gap_issued'] = round((target / closing - 1) * 100, 1)
            panel['price_move'] = round((current / closing - 1) * 100, 1)

    cut = today - timedelta(days=CYCLE_DAYS)
    recent = [r for r in rows if r[0] >= cut]
    panel['recent_n'] = len(recent)

    # 컨센서스는 '증권사별 최신 목표가'의 평균이다. 창 안의 리포트를 전부
    # 평균하면 상향 사이클에서 최신 목표가가 늘 평균 위로 나온다 — 몇 달 전의
    # 낮은 목표가들이 평균을 끌어내리기 때문이다. 그러면 의견 차이가 아니라
    # 시차를 재게 된다. 지금 각자 무슨 값을 부르고 있는지를 봐야 한다.
    if recent:
        by_provider = {}
        for _, prov, tp in recent:      # 날짜 오름차순이라 뒤가 최신
            by_provider[prov] = tp
        panel['consensus'] = round(sum(by_provider.values()) / len(by_provider))
        panel['providers'] = len(by_provider)
        if panel['consensus']:
            panel['consensus_gap'] = round((target / panel['consensus'] - 1) * 100, 1)
            panel['outlier'] = (panel['providers'] >= CONSENSUS_MIN_PROVIDERS
                                and abs(panel['consensus_gap']) >= CONSENSUS_OUTLIER)

    # 방향은 같은 증권사의 직전 목표가와만 견준다. 증권사마다 목표가를 잡는
    # 수준이 달라서, 남의 목표가와 비교하면 방향이 아니라 시각차가 나온다.
    seen = {}
    for d, prov, tp in rows:
        before = seen.get(prov)
        seen[prov] = tp
        if before is None or d < cut:
            continue
        if tp > before * (1 + CYCLE_MOVE / 100):
            panel['up'] += 1
        elif tp < before * (1 - CYCLE_MOVE / 100):
            panel['down'] += 1
        else:
            panel['flat'] += 1

    panel['reading'] = _reading(panel)
    return panel


def _reading(p):
    """숫자 셋을 한 줄로. 화면에 그대로 나가는 문장이다."""
    gap, move = p['gap_now'], p['price_move']
    if gap is None:
        return ''

    parts = []
    # 오래된 리포트는 지금 상황을 안 담고 있다. 괴리율을 읽기 전에 말해줘야
    # 한다 — 넉 달 전 목표가로 계산한 "+90% 여력"을 오늘의 판단으로 쓰게 된다.
    if p['recent_n'] == 0:
        parts.append(f'마지막 리포트가 {p["age"]}일 전이다. 최근 {CYCLE_DAYS}일 새로 '
                     f'나온 것이 없어 위 숫자는 그때의 시각이지 지금의 시각이 아니다.')

    if gap < GAP_OVERSHOOT:
        parts.append('주가가 목표가를 넘어섰다. 애널리스트가 더 볼 것이 없다고 한 '
                     '자리를 지나온 셈이라, 목표가 상향이 따라오는지가 관건이다.')
    elif gap <= GAP_THIN:
        parts.append('목표가에 거의 다 왔다. 남은 여력이 한 자리다.')
    elif gap >= GAP_STRONG and move is not None and move < 0:
        parts.append('여력이 커 보이지만 발행 뒤 주가가 빠져서 벌어진 것이다. '
                     '목표가는 주가에 후행해 뒤늦게 내려온다.')
    elif gap >= GAP_STRONG:
        parts.append('발행 때부터 크게 지른 콜인데 주가가 아직 안 따라왔다. '
                     '시장이 논거를 아직 안 받아들이고 있다는 뜻이기도 하다.')
    else:
        parts.append('한국 리포트의 보통 수준이다. 이 숫자만으로는 읽을 것이 없다.')

    if p['outlier']:
        side = '위' if p['consensus_gap'] > 0 else '아래'
        parts.append(f'다만 이 목표가는 증권사 {p["providers"]}곳 평균보다 '
                     f'{abs(p["consensus_gap"]):.0f}% {side}라 혼자 튄 값이다.')

    up, down, flat = p['up'], p['down'], p['flat']
    if up + down + flat >= 3:
        if down > up:
            parts.append(f'최근 {CYCLE_DAYS}일 목표가는 하향 {down}건이 상향 {up}건보다 '
                         f'많다. 괴리율보다 이 방향을 먼저 봐야 한다.')
        elif up >= 3 and up > down * 2:
            parts.append(f'최근 {CYCLE_DAYS}일 목표가는 상향 {up}건으로 우세하다. '
                         f'논거가 아직 살아 있다.')
        else:
            parts.append(f'최근 {CYCLE_DAYS}일 목표가 방향은 상향 {up} · 하향 {down}으로 '
                         f'뚜렷하지 않다.')
    return ' '.join(parts)
