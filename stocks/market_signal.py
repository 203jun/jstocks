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

# ADR 출처. 카드에서 눌러 원본을 확인할 수 있게 한다 (HTTPS 미지원 사이트)
ADR_SOURCE_URL = 'http://adrinfo.kr/'

# 임계선 근처에서 값이 넘나들면 상태 변화가 5일에 한 번씩 생겨 로그가 노이즈로
# 가득 찬다. 새 상태가 이만큼 유지돼야 '변화'로 인정한다 (104건 -> 44건).
EVENT_MIN_DAYS = 3

# 상태 변화 로그와 지속 일수를 계산할 범위. 늘어나도 조회가 무거워지지 않게 자른다.
HISTORY_LIMIT = 750

# save_market_indicator 와 같은 값. 백분위 표본이 몇 일인지 화면에 밝히는 데 쓴다.
PERCENTILE_WINDOW = 250

# 카드 팝업의 미니 차트 길이. 반년쯤이면 지금 자리가 어디인지 눈으로 잡힌다.
DETAIL_SERIES_DAYS = 120

# 팝업에 나열할 최근 구간 개수
DETAIL_EPISODE_LIMIT = 5

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
            'foreign_net_20d_pct', 'ma200_gap_pct', 'disparity_pct',
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

    date, disparity, adr, foreign, gap, foreign_pct, gap_pct, disparity_pct = rows[-1]
    # 게이지 폭은 조회 범위 안의 실제 최대치에서 잡는다.
    # 코스피와 코스닥의 수급 규모가 10배 넘게 차이나 공통 눈금을 쓸 수 없다.
    foreign_span = max((abs(r[3]) for r in rows if r[3] is not None), default=0)
    gap_span = max((abs(r[4]) for r in rows if r[4] is not None), default=0)

    # 백분위를 낸 표본 크기. 창(250일)이 꽉 차기 전에는 값이 흔들리므로 화면에 밝힌다.
    samples = {
        'disparity': min(sum(1 for r in rows if r[1] is not None), PERCENTILE_WINDOW),
        'foreign': min(sum(1 for r in rows if r[3] is not None), PERCENTILE_WINDOW),
        'ma200': min(sum(1 for r in rows if r[4] is not None), PERCENTILE_WINDOW),
    }

    cards = _build_cards(
        disparity, adr, foreign, gap, disparity_pct, foreign_pct, gap_pct,
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
        # 카드 팝업 (JS 가 채운다). 카드의 action 키와 이름을 맞춰 둔다.
        'details': {
            'disparity-detail': _disparity_detail(
                rows, (dis_low, dis_high), disparity_pct, samples['disparity'], streaks
            ),
            'ma200-detail': _ma200_detail(rows, gap_pct, samples['ma200'], streaks),
        },
    }


def _card(label, value, delta, state, badge, streak, gauge, link='', action=''):
    """
    link   : 누르면 새 탭으로 여는 외부 주소
    action : 누르면 화면 안에서 처리할 동작 (JS 가 data-action 으로 받는다)
    """
    return {
        'label': label, 'value': value, 'delta': delta,
        'state': state, 'badge': badge, 'streak': streak,
        'link': link, 'action': action, **gauge,
    }


def _streak_text(streaks, key):
    _, days, capped = streaks[key]
    if not days:
        return ''
    return f'{days}일+' if capped else f'{days}일째'


def _percentile_text(pct, sample):
    """
    백분위를 상위/하위로 뒤집어 적는다. "백분위 75%"는 높은 쪽인지 낮은 쪽인지
    한 번 더 생각해야 하지만 "상위 25%"는 바로 읽힌다.

    창이 꽉 차기 전에는 값이 흔들리므로 표본 수를 함께 적는다.
    (꽉 찬 뒤에는 늘 250이라 굳이 반복하지 않는다)
    """
    if pct is None:
        return ''
    value = float(pct)
    # 0%/100% 는 "상위 0%" 처럼 어색해지므로 1% 를 바닥으로 둔다
    if value >= 50:
        text = f'상위 {max(1, round(100 - value))}%'
    else:
        text = f'하위 {max(1, round(value))}%'
    if sample < PERCENTILE_WINDOW:
        text += f' · 표본 {sample}일'
    return text


def _build_cards(disparity, adr, foreign, gap, disparity_pct, foreign_pct, gap_pct,
                 dis_th, adr_th, foreign_span, gap_span, streaks, samples):
    cards = []

    if disparity is not None:
        low, high = dis_th
        state, badge = (('warn', '과열') if disparity >= high else
                        ('chance', '침체') if disparity <= low else ('neutral', '중립'))
        # 이격도는 평균회귀 계열이라 백분위 분포가 고르다(중앙 51~52, 상위 20%
        # 구간이 관측 24~27%). 200일선과 달리 백분위를 그대로 믿고 읽어도 된다.
        cards.append(_card('이격도', f'{disparity:,.2f}',
                           _percentile_text(disparity_pct, samples['disparity']),
                           state, badge,
                           _streak_text(streaks, 'disparity'),
                           _banded_gauge(disparity, low, high),
                           action='disparity-detail'))

    if adr is not None:
        low, high = adr_th
        state, badge = (('warn', '과열') if adr >= high else
                        ('chance', '바닥권') if adr <= low else ('neutral', '중립'))
        cards.append(_card('ADR', f'{adr:,.2f}', '', state, badge,
                           _streak_text(streaks, 'adr'),
                           _banded_gauge(adr, low, high),
                           link=ADR_SOURCE_URL))

    if foreign is not None:
        state, badge = (('ok', '순매수') if foreign > 0 else
                        ('warn', '순매도') if foreign < 0 else ('neutral', '중립'))
        cards.append(_card('외인 20일', _fmt_eok(foreign),
                           _percentile_text(foreign_pct, samples['foreign']),
                           state, badge,
                           _streak_text(streaks, 'foreign'),
                           _zero_gauge(foreign, foreign_span),
                           action='trend-detail'))

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
                           _zero_gauge(gap, gap_span),
                           action='ma200-detail'))

    return cards


def _episodes(seq, in_band, pick):
    """
    in_band(값)이 참인 연속 구간을 뽑는다.
    마지막 구간이 오늘까지 이어지면 open=True (아직 안 끝나서 길이가 잘려 있다).
    """
    out, run = [], None
    for date, value in seq:
        if in_band(value):
            if run is None:
                run = {'from': date, 'to': date, 'days': 1, 'peak': value}
            else:
                run.update(to=date, days=run['days'] + 1, peak=pick(run['peak'], value))
        elif run:
            out.append(run)
            run = None
    if run:
        run['open'] = True
        out.append(run)
    return out


def _build_band_detail(seq, title, streak, pct, sample, bands, fmt,
                       marks, shade=None, caution=''):
    """
    지표 카드 팝업의 공용 뼈대 (이격도 · 200일선).

    값 하나만으로는 아무 느낌이 없는 지표들이라 세 가지를 붙인다.
      1. 분포 위치 — 최근 250일 중 이보다 높았던 날이 몇 일인가
      2. 지속성   — 지금 구간이 며칠째이고, 과거엔 보통 며칠 갔나
      3. 추이     — 최근 120일 그림 (임계선과 함께)

    2번은 수익률 예측이 아니라 지속 기간 통계다. 이력이 2년 반뿐이라
    "이랬을 때 20일 뒤 수익률" 같은 건 표본이 사실상 에피소드 1~2개라
    쓰지 않는다 (상승확률 93% 같은 숫자가 나와 오히려 부추긴다).

    인자:
      seq    : [(date, value)] 오래된 것부터, None 제거된 상태
      streak : (상태키, 일수) — 카드 배지와 같은 값
      bands  : [(키, 라벨, 규칙설명, 판정함수, 극값선택함수)]
      fmt    : 값 포맷 함수
      marks  : 스파크라인에 그을 임계선 [{'v':, 'color':, 'label':}]
      shade  : 옅게 칠할 구간 {'from':, 'to':} 또는 None
      caution: 백분위를 곧이곧대로 읽으면 안 되는 지표의 경고문
    """
    if not seq:
        return None

    value = seq[-1][1]
    window = seq[-PERCENTILE_WINDOW:]
    state, streak_days = streak

    stats, recent, labels = [], [], {}
    for key, label, rule, test, pick in bands:
        labels[key] = label
        eps = _episodes(seq, test, pick)
        # 진행 중인 구간은 길이가 잘려 있어 '평균'에서만 뺀다.
        # 최장까지 빼면 오독이 심해진다 — 200일선 위 국면이 235일째인데 끝난 것만
        # 세면 "평균 8일, 최장 9일"이 되어 오래 못 가는 상태처럼 읽힌다.
        # 진행 중인 구간은 최소한 그만큼은 갔다는 뜻이므로 최장에는 넣고 + 를 붙인다.
        closed = [e for e in eps if not e.get('open')]
        ongoing = next((e for e in eps if e.get('open')), None)
        longest = max((e['days'] for e in eps), default=0)
        stats.append({
            'key': key, 'label': label, 'rule': rule,
            'count': len(eps),
            'avg': round(sum(e['days'] for e in closed) / len(closed)) if closed else 0,
            'max': longest,
            'max_open': bool(ongoing and ongoing['days'] == longest),
        })
        for e in eps:
            recent.append({**e, 'key': key, 'label': label})

    recent.sort(key=lambda e: e['to'], reverse=True)

    return {
        'title': title,
        'value': fmt(value),
        'pct_text': _percentile_text(pct, sample),
        'above': sum(1 for _, v in window if v > value),
        'sample': len(window),
        'state': state,
        'state_label': labels.get(state, '중립'),
        'streak': streak_days,
        'caution': caution,
        'marks': marks,
        'shade': shade,
        'stats': stats,
        'recent': [
            {
                'label': e['label'], 'key': e['key'],
                'from': e['from'].strftime('%y.%m.%d'),
                'to': '진행 중' if e.get('open') else e['to'].strftime('%y.%m.%d'),
                'days': e['days'],
                'peak': fmt(e['peak']),
            }
            for e in recent[:DETAIL_EPISODE_LIMIT]
        ],
        'series': [
            {'d': d.strftime('%Y-%m-%d'), 'v': float(v)}
            for d, v in seq[-DETAIL_SERIES_DAYS:]
        ],
        'span': {
            'from': seq[0][0].strftime('%Y-%m-%d'),
            'to': seq[-1][0].strftime('%Y-%m-%d'),
            'days': len(seq),
        },
    }


def _disparity_detail(rows, dis_th, pct, sample, streaks):
    low, high = dis_th
    state, days, _ = streaks['disparity']
    return _build_band_detail(
        seq=[(r[0], r[1]) for r in rows if r[1] is not None],
        title='이격도 (20일)',
        streak=(state, days),
        pct=pct, sample=sample,
        bands=[
            ('hot', '과열', f'≥ {high:g}', lambda v: v >= high, max),
            ('cold', '침체', f'≤ {low:g}', lambda v: v <= low, min),
        ],
        fmt=lambda v: f'{v:,.2f}',
        marks=[{'v': float(high), 'color': 'up', 'label': f'{high:g}'},
               {'v': float(low), 'color': 'down', 'label': f'{low:g}'}],
        shade={'from': float(low), 'to': float(high)},
    )


def _ma200_detail(rows, pct, sample, streaks):
    state, days, _ = streaks['ma200']
    return _build_band_detail(
        seq=[(r[0], r[4]) for r in rows if r[4] is not None],
        title='200일선 대비',
        # 카드와 같은 부호 상태를 쓰되, 색은 이격도와 통일한다 (위=빨강, 아래=파랑)
        streak=({'plus': 'hot', 'minus': 'cold'}.get(state, state), days),
        pct=pct, sample=sample,
        bands=[
            # '< 0%' 처럼 꺾쇠를 쓰면 innerHTML 에서 태그 시작으로 읽힐 수 있다
            ('hot', '위', '0% 초과', lambda v: v > 0, max),
            ('cold', '아래', '0% 미만', lambda v: v < 0, min),
        ],
        fmt=lambda v: f'{v:+,.2f}%',
        marks=[{'v': 0.0, 'color': 'zero', 'label': '0%'}],
        caution='200일선 이격은 추세 시계열이라 상승장에서는 백분위가 계속 '
                '상단에 붙어 있습니다(관측 75~78%). 과열 신호로 읽지 마세요.',
    )


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


# --------------------------------------------------------------------- #
# AI 프롬프트용 텍스트
# --------------------------------------------------------------------- #

def _prompt_table(panel):
    """카드 4개를 프롬프트에 붙일 표로. 화면과 같은 값을 그대로 쓴다."""
    if not panel:
        return '(데이터 없음)'
    lines = []
    for c in panel['cards']:
        badge = c['badge'] + (f" {c['streak']}" if c['streak'] else '')
        lines.append(f"- {c['label']}: {c['value']}"
                     + (f" ({c['delta']})" if c['delta'] else '')
                     + f" · {badge}")
    return '\n'.join(lines)


def _prompt_events(panel):
    if not panel or not panel['events']:
        return f'- 최근 {EVENT_MIN_DAYS}거래일 이상 유지된 상태 변화 없음'
    return '\n'.join(
        f"- {e['date']:%m/%d} {e['text']} ({e['ago']}일 전)" for e in panel['events']
    )


MARKET_NAMES = {'KOSPI': '코스피', 'KOSDAQ': '코스닥'}


def _with_particle(word, with_batchim, without_batchim):
    """받침 유무로 조사를 고른다 (코스피는 / 코스닥은)"""
    last = word[-1]
    has_batchim = '가' <= last <= '힣' and (ord(last) - 0xAC00) % 28
    return word + (with_batchim if has_batchim else without_batchim)


def _prompt_reading_guide(market):
    """
    화면에는 안 보이지만 값을 읽을 때 반드시 알아야 하는 규칙들.

    AI 가 이걸 모르면 엉뚱하게 읽는다 — 코스닥 이격도 106 을 코스피 기준(105)으로
    과열이라 하거나, 200일선 백분위 상위 7% 를 과열 신호로 잡거나, 어제 생긴
    전환이 로그에 없다고 "변화 없음"으로 단정한다.

    임계값이 바뀌면 문구도 같이 바뀌도록 상수에서 만들어 쓴다.
    시장마다 프롬프트가 따로라 그 시장 임계값만 적는다.
    """
    name = MARKET_NAMES.get(market, market)
    low, high = DISPARITY_THRESHOLDS.get(market, DISPARITY_THRESHOLDS['KOSPI'])
    adr_low, adr_high = ADR_THRESHOLDS
    other = 'KOSDAQ' if market == 'KOSPI' else 'KOSPI'
    other_low, other_high = DISPARITY_THRESHOLDS[other]
    return '\n'.join([
        f'- 이격도 임계값은 {name} 기준 {low:g}/{high:g} 다. 시장마다 다르며 '
        f'{_with_particle(MARKET_NAMES[other], "은", "는")} {other_low:g}/{other_high:g} 다'
        f' — 코스닥이 더 크게 흔들려서다.',
        f'- ADR 은 등락비율이다. {adr_low:g} 이하 바닥권, {adr_high:g} 이상 과열.',
        '- 외국인 20일 누적은 최근 20거래일 순매수 합계(억원)다.',
        f'- 괄호 안 백분위는 최근 {PERCENTILE_WINDOW}거래일 중 위치다. '
        f'"상위 2%" 는 2년 가까이 그만큼밖에 없던 자리라는 뜻이다.',
        '- 단 200일선 대비 백분위는 예외다. 추세 시계열이라 상승장에서는 계속 '
        '상단에 붙어 있다(관측 75~78%). 과열 신호로 읽지 마라.',
        f'- 상태 변화 로그는 새 상태가 {EVENT_MIN_DAYS}거래일 이상 유지돼야 올라온다. '
        f'최근 1~2일 안에 생긴 전환은 아직 안 보일 수 있다.',
        f'- 이 지표들은 {name} 전체 판단용이다. 개별 종목의 좋고 나쁨은 말해주지 않는다.',
    ])


def build_prompt_vars(market, panel, today):
    """
    {변수} -> 채워 넣을 값. 화면(JS)이 이 사전으로 치환한다.
    코스피/코스닥이 각자 다른 프롬프트를 쓰므로 시장 하나짜리로 만든다.
    """
    return {
        '{시장}': MARKET_NAMES.get(market, market),
        '{오늘날짜}': today.strftime('%Y-%m-%d'),
        '{기준일}': panel['date'].strftime('%Y-%m-%d') if panel else '(없음)',
        '{지표}': _prompt_table(panel),
        '{상태변화}': _prompt_events(panel),
        '{읽는법}': _prompt_reading_guide(market),
    }
