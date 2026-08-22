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

# ── 슬롯용 임계값 ──────────────────────────────────────────────────
#
# 종목 화면의 배지는 늘 같은 자리에 있고 켜질 때만 색이 붙는다. 그러려면
# 꺼져 있는 것이 기본이어야 한다 — 절반이 켜지면 계기판이 아니라 그냥 표다.
# 관심종목 47개로 재보고 조인 값들이다.
#
#   눌림목  과열 36% · 추세중 9% 를 끈다. 둘 다 '지금 사라'가 아니라
#           '지금 자리'일 뿐이고, 켜져 있으면 진짜 눌림(4%)이 묻힌다.
#   수급    3일 연속이 17~28% 로 흔했다. 5일로 올리면 한 자릿수가 된다.
#   장대양봉 20일 신고까지 잡아 36% 였다. 60일 신고만 센다.
SLOT_PULLBACK_ON = ('얕은눌림', '깊은눌림', '이탈')
SLOT_STREAK_MIN = 5
SLOT_GAP_STRONG = 50     # 괴리율이 이만큼 크면 세게 지른 콜
SLOT_GAP_THIN = 10       # 이만큼 작으면 애널리스트도 여력을 못 봤다


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


def investor_flow(values, streak_min=SLOT_STREAK_MIN):
    """
    슬롯용 — 사는 쪽인지 파는 쪽인지까지 본다. (글자, 방향) 없으면 None.

    investor_streaks 는 사는 쪽만 세고 메인 현황 표가 쓴다. 여기서는 파는
    쪽도 신호다 — 기관이 엿새 연속 던지는 것은 살 자리가 아니라는 뜻이다.
    """
    if not values or not values[0]:
        return None
    if values[0] > 0 and values[0] >= max(values):
        return (f'{STREAK_WINDOW}일 최대', 'up')
    if values[0] < 0 and values[0] <= min(values):
        return (f'{STREAK_WINDOW}일 최소', 'down')
    buying = values[0] > 0
    days = 0
    for v in values:
        if v and (v > 0) == buying:
            days += 1
        else:
            break
    if days < streak_min:
        return None
    return (f'{days}일 연속', 'up' if buying else 'down')


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


# 장대양봉을 찾는 창. 그날 이후 얼마나 밀렸는지가 지금 살 자리인지를 말한다.
BIG_CANDLE_WINDOW = 10

# 52주 고점에 이만큼 붙으면 신고가로 본다. 딱 갱신한 날만 세면 거의 안 걸린다.
NEW_HIGH_MARGIN = 1.0


def volume_high(daily):
    """오늘 거래량이 60일·20일 최대인가. ('60일'|'20일'|'')"""
    if not daily or not daily[0].trading_volume:
        return ''
    today = daily[0].trading_volume
    if len(daily) >= 60 and today >= max(d.trading_volume for d in daily[:60]):
        return '60일'
    if len(daily) >= 20 and today >= max(d.trading_volume for d in daily[:20]):
        return '20일'
    return ''


def big_candle(daily):
    """
    최근 장대양봉과 그 뒤 등락. 없으면 None.

    장대양봉 = 신고거래량(60일 우선, 없으면 20일) + 양봉 + 20일선 위.
    돈이 크게 들어온 날이다. 그날 이후 얼마나 밀렸는지가 지금 자리를 말한다 —
    안 밀렸으면 따라붙는 것이고, 많이 밀렸으면 그날의 힘이 꺾인 것이다.
    """
    if len(daily) < 65:
        return None
    for i in range(BIG_CANDLE_WINDOW):
        day = daily[i]
        if day.closing_price < day.opening_price:
            continue
        ma20_rows = daily[i:i + 20]
        if len(ma20_rows) < 20:
            continue
        if day.closing_price <= sum(d.closing_price for d in ma20_rows) / 20:
            continue
        vol60, vol20 = daily[i:i + 60], daily[i:i + 20]
        is60 = (len(vol60) >= 60 and day.trading_volume
                and day.trading_volume == max(d.trading_volume for d in vol60))
        is20 = (not is60 and len(vol20) >= 20 and day.trading_volume
                and day.trading_volume == max(d.trading_volume for d in vol20))
        if not (is60 or is20):
            continue
        move = (round((daily[0].closing_price / day.closing_price - 1) * 100, 1)
                if day.closing_price else 0)
        return {'days_ago': i, 'date': day.date, 'move': move,
                'kind': '60일' if is60 else '20일'}
    return None


def new_high(daily):
    """52주 고점 대비 %. (고점, 대비 %, 신고가 여부)"""
    if not daily:
        return None
    year = daily[:250]
    high = max((d.high_price for d in year if d.high_price), default=None)
    if not high:
        return None
    gap = round((daily[0].closing_price / high - 1) * 100, 1)
    return {'high': high, 'gap': gap, 'is_new': gap >= -NEW_HIGH_MARGIN}


def new_low(daily):
    """52주 저점 대비 %. 고점과 대칭이다."""
    if not daily:
        return None
    year = daily[:250]
    low = min((d.low_price for d in year if d.low_price), default=None)
    if not low:
        return None
    gap = round((daily[0].closing_price / low - 1) * 100, 1)
    return {'low': low, 'gap': gap, 'is_new': gap <= NEW_HIGH_MARGIN}


ALIGN_NAMES = {'bull': '정배열', 'bear': '역배열', 'mixed': '뒤섞임'}


# ── 슬롯 아홉 칸 ──────────────────────────────────────────────────
#
# 자리가 늘 같아야 모양만 보고 읽게 된다. 켜지면 색이 붙고, 꺼지면 칸 이름이
# 아주 흐리게 남는다 — 빈칸으로 두면 '오늘 조용하다'와 '자료가 없다'가
# 구별되지 않는다.
#
# 색은 둘뿐이다. 빨강은 기회, 파랑은 경고.
SLOT_ROWS = [
    ('신호', ['눌림목', '거래량', '장대양봉', '고저']),
    ('수급', ['외국인', '기관']),
    ('리포트', ['리포트', '공시', '괴리율']),
]


def _slot(text, tone):
    return {'on': True, 'text': text, 'tone': tone}


def build_slots(stock, daily, inv_data, report_count, gongsi_good, gongsi_bad,
                window_days):
    """
    화면에 뿌릴 아홉 칸. 켜진 것만 값이 들어 있고 나머지는 None.

    daily 는 최신이 앞. inv_data 도 최신이 앞(최근 20거래일).
    """
    out = {}

    # ── 눌림목 — 정배열에서 20일선까지 밀린 자리. 과열·추세중은 끈다.
    align = ma_alignment(daily)
    gap, label = pullback(daily, align)
    out['눌림목'] = (_slot(f'{label} {gap:+.1f}%', 'down' if label == '이탈' else 'up')
                  if label in SLOT_PULLBACK_ON else None)

    # ── 거래량 — 오늘 신고거래량인가. 양봉이면 기회, 음봉이면 경고.
    vh = volume_high(daily)
    if vh and daily:
        rising = daily[0].closing_price >= daily[0].opening_price
        out['거래량'] = _slot(f'{vh} 신고', 'up' if rising else 'down')
    else:
        out['거래량'] = None

    # ── 장대양봉 — 돈이 크게 들어온 날 이후 며칠, 그 뒤 얼마나 밀렸나.
    #    60일 신고만 센다. 20일 신고까지 잡으면 셋에 하나가 걸린다.
    bc = big_candle(daily)
    if bc and bc['kind'] == '60일':
        if bc['days_ago'] == 0:
            out['장대양봉'] = _slot('오늘', 'up')
        else:
            out['장대양봉'] = _slot(f'{bc["days_ago"]}일 {bc["move"]:+.1f}%',
                                 'down' if bc['move'] < 0 else 'up')
    else:
        out['장대양봉'] = None

    # ── 고저 — 52주 고점·저점에 닿았나.
    nh = new_high(daily)
    low = new_low(daily)
    if nh and nh['is_new']:
        out['고저'] = _slot('52주 신고가', 'up')
    elif low and low['is_new']:
        out['고저'] = _slot('52주 신저가', 'down')
    else:
        out['고저'] = None

    # ── 수급 — 사는 쪽도 파는 쪽도 신호다.
    out['외국인'] = out['기관'] = None
    if inv_data:
        for key, name in (('foreign', '외국인'), ('institution', '기관')):
            flow = investor_flow([getattr(d, key) for d in inv_data])
            out[name] = _slot(*flow) if flow else None

    # ── 리포트·공시 — 창 안에 새로 나온 것.
    out['리포트'] = _slot(f'{report_count}건', 'up') if report_count else None
    if gongsi_bad:
        text = f'악재 {gongsi_bad}' + (f' · 호재 {gongsi_good}' if gongsi_good else '')
        out['공시'] = _slot(text, 'down')
    elif gongsi_good:
        out['공시'] = _slot(f'호재 {gongsi_good}', 'up')
    else:
        out['공시'] = None

    # ── 괴리율 — 드문 양끝만 켠다. 가운데(+21~39%)는 증권사 관행이라
    #    읽어봐야 얻을 것이 없다.
    gap_now = report_gap(stock)
    if gap_now is None:
        out['괴리율'] = None
    elif gap_now >= SLOT_GAP_STRONG:
        out['괴리율'] = _slot(f'{gap_now:+.1f}%', 'up')
    elif gap_now <= SLOT_GAP_THIN:
        out['괴리율'] = _slot(f'{gap_now:+.1f}%', 'down')
    else:
        out['괴리율'] = None

    rows = [{'name': name, 'slots': [{'key': k, **(out[k] or {'on': False})} for k in keys]}
            for name, keys in SLOT_ROWS]
    return {'rows': rows, 'window': window_days, 'gap_now': gap_now,
            'align': align, 'align_name': ALIGN_NAMES.get(align, '')}
