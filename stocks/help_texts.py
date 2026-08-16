# -*- coding: utf-8 -*-
"""
ⓘ 아이콘을 눌렀을 때 뜨는 설명들.

화면에 숫자만 있으면 "이게 뭘로 계산한 거고 기준이 뭐였지"를 매번 다시 떠올려야
한다. 설명은 여기 한 곳에만 두고, 템플릿에서는 {% help_icon "키" %} 한 줄로 붙인다.

임계값처럼 코드에 이미 있는 값은 그 상수에서 만들어 쓴다. 문구와 실제 동작이
어긋나는 일을 막기 위해서다 — 설명이 틀리면 없느니만 못하다.

본문은 여러 줄 문자열이며 화면에서 줄바꿈 그대로 보여준다(white-space: pre-line).
"""


def _disparity(market=None):
    from .market_signal import DISPARITY_THRESHOLDS, MARKET_NAMES, PERCENTILE_WINDOW

    lines = ['종가 ÷ 20일 이동평균 × 100', '', '20일선에서 얼마나 떨어져 있는지를 본다. '
             '100이면 딱 20일선 위, 110이면 10% 위에 떠 있다는 뜻이다.', '']
    for code, (low, high) in DISPARITY_THRESHOLDS.items():
        mark = '▸ ' if code == market else '  '
        lines.append(f'{mark}{MARKET_NAMES[code]}: {high:g} 이상 과열, {low:g} 이하 침체')
    lines += [
        '',
        '코스닥이 더 크게 흔들려서 기준을 넓게 잡았다.',
        '',
        f'백분위는 최근 {PERCENTILE_WINDOW}거래일 중 오늘 값의 위치다. '
        f'이격도는 평균으로 되돌아오는 성질이라 백분위 분포가 고르고, '
        f'그래서 "상위 몇 %"를 그대로 믿고 읽어도 된다.',
    ]
    return '\n'.join(lines)


def _adr(market=None):
    from .market_signal import ADR_SOURCE_URL, ADR_THRESHOLDS

    low, high = ADR_THRESHOLDS
    return '\n'.join([
        '등락비율(Advance Decline Ratio)',
        '',
        '오른 종목 수 ÷ 내린 종목 수 × 100 을 일정 기간 누적한 값이다.',
        '지수는 몇몇 대형주가 끌어올릴 수 있지만 ADR은 시장 전체가 '
        '같이 올랐는지를 보여준다.',
        '',
        f'  {high:g} 이상 과열',
        f'  {low:g} 이하 바닥권',
        '',
        f'출처: {ADR_SOURCE_URL} (직접 계산하지 않고 수집한 값이다)',
    ])


def _foreign(market=None):
    from .market_signal import PERCENTILE_WINDOW

    return '\n'.join([
        '외국인 20일 누적 순매수',
        '',
        '최근 20거래일 동안 외국인이 사고판 금액의 합계다. '
        '양수면 순매수, 음수면 순매도.',
        '',
        '하루치는 들쭉날쭉해서 방향을 못 읽는다. 20일로 묶으면 '
        '"지금 외국인이 들어오는 중인가 나가는 중인가"가 보인다.',
        '',
        '── 백분위 ──',
        '',
        '거래일마다 그날까지의 20일 누적값이 하나씩 나온다. '
        f'최근 {PERCENTILE_WINDOW}거래일치, 즉 20일 누적값 {PERCENTILE_WINDOW}개를 '
        f'크기순으로 줄 세운 뒤 오늘 값이 몇 번째인지 본 것이다.',
        '',
        '하루치끼리 비교하는 게 아니라 20일 누적값끼리 비교한다.',
        '',
        '"상위 25%"라면 지난 1년의 20일 누적값 중 오늘보다 큰 날이 '
        '4분의 1밖에 없었다는 뜻이다.',
        '',
        '금액만으로는 큰지 작은지 알 수 없어서 붙였다. 지난 1년이 내내 '
        '순매도였다면 크지 않은 순매수도 상위권에 들어간다 — 그 시장에서는 '
        '그게 실제로 드문 일이기 때문이다.',
        '',
        '출처: 네이버 금융 투자자별 매매동향 (단위: 억원)',
    ])


def _ma200(market=None):
    return '\n'.join([
        '(종가 ÷ 200일 이동평균 − 1) × 100',
        '',
        '200일선 위면 강세, 아래면 약세로 본다. 단기 등락이 아니라 '
        '지금이 어느 국면인지를 가르는 선이다.',
        '',
        '이 지표는 과열/침체를 판정하지 않는다.',
        '',
        '백분위가 붙어 있지만 곧이곧대로 읽으면 안 된다. 200일선 이격은 '
        '한 방향으로 오래 가는 추세 시계열이라, 상승장에서는 백분위가 계속 '
        '상단에 붙어 있다(관측 75~78%). 과열 신호로 쓰면 양치기가 된다.',
        '',
        '값과 백분위는 참고로만 보고, 판단은 위/아래와 그 국면이 며칠째인지로 한다.',
    ])


def _events(market=None):
    from .market_signal import EVENT_MIN_DAYS

    return '\n'.join([
        '지표의 상태가 바뀐 시점을 모아둔 기록이다.',
        '',
        f'임계선 근처에서 값이 넘나들면 며칠에 한 번씩 "전환"이 생겨 로그가 '
        f'노이즈로 가득 찬다. 그래서 새 상태가 {EVENT_MIN_DAYS}거래일 이상 '
        f'유지돼야 기록한다.',
        '',
        f'그 대신 오늘·어제 막 바뀐 것은 아직 안 올라온다. 카드 배지의 '
        f'"○○ 1일째"가 로그보다 빠르다.',
        '',
        '기록하는 변화',
        '  이격도 · ADR — 과열권/침체권 진입과 해소',
        '  외국인 — 순매수 ↔ 순매도 전환',
        '  200일선 — 상향 돌파 / 하향 이탈',
        '',
        '최근 5건만 보여준다.',
    ])


def _signal(market=None):
    from .market_signal import BEAR_NOTE, SIGNAL_LEVELS

    lines = [
        '이격도 · ADR · 외국인 수급을 합쳐 "지금 참아야 할 이유가 얼마나 있나"를 '
        '5단계로 나눈 것이다.',
        '',
    ]
    lines += [f'  {emoji} {name} — {message}' for _, emoji, name, message in SIGNAL_LEVELS]
    lines += [
        '',
        '200일선은 이 점수에 더하지 않는다. 합산에 넣으면 약세장일수록 점수가 '
        '내려가 "기회"로 밀려나는데, 200일선의 역할은 정확히 그 반대다.',
        '',
        f'대신 200일선 아래일 때 한 단계 신중한 쪽으로 당기고 이렇게 덧붙인다.',
        f'  "{BEAR_NOTE}"',
    ]
    return '\n'.join(lines)


def _cumulative(market=None):
    return '\n'.join([
        '지수 차트 아래에 겹쳐 그린 외국인·기관 누적 순매수다.',
        '',
        '고른 기간의 첫날부터 0에서 다시 쌓는다. 그래서 20일과 120일에서 '
        '선의 모양이 다르다 — 같은 데이터를 다른 시작점에서 본 것이다.',
        '',
        '지수가 오르는데 외국인 누적선이 내려가면 개인이 받아내고 있다는 뜻이다.',
        '',
        '출처: 네이버 금융 (단위: 억원, 장 마감 후 수집)',
    ])


HELP_TEXTS = {
    'disparity': {'title': '이격도 (20일)', 'body': _disparity},
    'adr': {'title': 'ADR', 'body': _adr},
    'foreign': {'title': '외국인 20일 누적 순매수', 'body': _foreign},
    'ma200': {'title': '200일선 대비', 'body': _ma200},
    'events': {'title': '최근 변화', 'body': _events},
    'signal': {'title': '종합 신호', 'body': _signal},
    'cumulative': {'title': '누적 순매수', 'body': _cumulative},
}
