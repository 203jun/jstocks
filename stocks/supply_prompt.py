# -*- coding: utf-8 -*-
"""
수급·공매도를 보고 오늘 매매 판단을 묻는 프롬프트의 입력값.

원자료를 통째로 던지고 AI 에게 계산시키면 틀린다. 이미 정규화해둔 값
(지분율, Z, 전환 표식)을 주고, 그 값을 어떻게 읽어야 하는지도 함께 준다.
{읽는법}이 그 자리다 — 임계값을 코드에서 만들어 넣으므로 기준을 바꾸면
프롬프트도 따라 바뀐다.

뉴스는 여기서 넣지 않는다. 프롬프트가 AI 에게 직접 찾아보라고 시킨다.
우리가 크롤링해 넣는 것보다 최신이고, 넣을 것을 고르는 수고도 없다.
"""
from .supply_signal import (
    FLOW_LONG_DAYS, FLOW_SHORT_DAYS, FLOW_STRONG, SHORT_Z_STRONG,
)

# 프롬프트 편집 창의 변수 칩. (이름, 설명)
SUPPLY_VARIABLES = [
    ('{종목명}', ''),
    ('{종목코드}', ''),
    ('{오늘날짜}', '데이터 기준일'),
    ('{현재가}', '현재가 · 등락률 · 거래량 전일비'),
    ('{수급요약}', '외국인·기관의 60일/20일 지분율과 전환 — 여러 줄'),
    ('{공매도요약}', '오늘 비중 · Z · 60일 통계 — 여러 줄'),
    ('{일별수급}', '최근 20거래일 표 — 여러 줄'),
    ('{투자자별}', '최근 5일 주체별 순매수 (연기금·투신·사모 등)'),
    ('{주가맥락}', '이동평균 대비 · 52주 고저 대비 — 여러 줄'),
    ('{리포트}', '목표가·컨센·방향과 최근 리포트 — 여러 줄'),
    ('{읽는법}', '임계값과 표식 규칙 (코드에서 자동 생성) — 여러 줄'),
]

# 키움 기준 주체별 필드. 기관을 하나로 뭉치면 연기금이 사는지 사모가 사는지
# 알 수 없다. 성격이 아주 다른 돈이다.
INVESTOR_FIELDS = [
    ('개인', 'individual'),
    ('외국인', 'foreign'),
    ('금융투자', 'financial'),
    ('투신', 'investment_trust'),
    ('연기금', 'pension_fund'),
    ('사모펀드', 'private_fund'),
    ('보험', 'insurance'),
    ('은행', 'bank'),
    ('기타법인', 'other_corporation'),
]

_EMPTY = '데이터 없음'


def _signed(value, unit=''):
    return f'{value:+,}{unit}' if value else f'0{unit}'


def _pct(value, unit='%'):
    return '-' if value is None else f'{value:+.2f}{unit}'


def _flow_line(label, dash, prefix):
    pct = dash.get(f'{prefix}_pct')
    if pct is None:
        return f'{label}  {_EMPTY}'
    amt = dash.get(f'{prefix}_amt') or 0
    pct20 = dash.get(f'{prefix}_pct20')
    mark = dash.get(f'{prefix}_turn') or ''
    line = (f'{label}  {FLOW_LONG_DAYS}일 {_pct(pct)} ({_signed(amt, "억")})'
            f' · {FLOW_SHORT_DAYS}일 {_pct(pct20)}')
    return line + (f'  [{mark}]' if mark else '')


def _supply_summary(dash):
    if not dash:
        return _EMPTY
    return '\n'.join([_flow_line('외국인', dash, 'foreign'),
                      _flow_line('기관  ', dash, 'inst')])


def _short_summary(dash, shorts_asc):
    if not dash or not shorts_asc:
        return _EMPTY
    window = shorts_asc[-min(len(shorts_asc), 60):]
    weights = [(float(s.trading_weight or 0), s.date) for s in window]
    high = max(weights)
    low = min(weights)
    avg = sum(w for w, _ in weights) / len(weights)
    value = sum((s.short_trading_value or 0) * 1000 for s in window)
    volume = sum(s.short_volume or 0 for s in window)
    lines = [
        f'오늘 비중 {dash["short_weight"]}%  (Z {dash["z_score"]})',
        f'{len(window)}일 평균 {avg:.2f}% · 최고 {high[0]:.2f}% ({high[1]:%m/%d})'
        f' · 최저 {low[0]:.2f}% ({low[1]:%m/%d})',
    ]
    if volume:
        lines.append(f'{len(window)}일 공매도 평균단가 {round(value / volume):,}원'
                     f' · 누적 대금 {round(value / 100000000):,}억')
    return '\n'.join(lines)


def _daily_table(trends_asc, shorts_map, charts_map, charts_asc, days=20):
    rows = trends_asc[-days:]
    if not rows:
        return _EMPTY
    # 등락률은 DailyChart 에 없다. 앞날 종가와 견줘 만든다.
    prev = {}
    for before, chart in zip(charts_asc, charts_asc[1:]):
        prev[chart.date] = before.closing_price

    out = ['날짜, 외국인, 기관, 개인, 공매도비중, 종가, 등락률']
    for t in rows:
        chart = charts_map.get(t.date)
        short = shorts_map.get(t.date)
        close = chart.closing_price if chart else 0
        before = prev.get(t.date)
        rate = f'{(close / before - 1) * 100:+.2f}%' if before and close else '-'
        out.append(', '.join([
            f'{t.date:%m/%d}',
            f'{t.daum_foreign or 0:+,}',
            f'{t.daum_institution or 0:+,}',
            f'{t.individual or 0:+,}',
            f'{float(short.trading_weight or 0):.2f}%' if short else '-',
            f'{close:,}',
            rate,
        ]))
    return '\n'.join(out)


def _investor_breakdown(trends_asc, days=5):
    rows = trends_asc[-days:]
    if not rows:
        return _EMPTY
    totals = []
    for label, field in INVESTOR_FIELDS:
        total = sum(getattr(t, field) or 0 for t in rows)
        if total:
            totals.append((abs(total), label, total))
    if not totals:
        return _EMPTY
    totals.sort(reverse=True)
    body = ' · '.join(f'{label} {value:+,}' for _, label, value in totals)
    return f'최근 {len(rows)}일 합계 (주)\n{body}'


def _price_context(charts_asc, stock):
    if len(charts_asc) < 20:
        return _EMPTY
    closes = [c.closing_price for c in charts_asc if c.closing_price]
    if not closes:
        return _EMPTY
    now = closes[-1]
    lines = []
    parts = []
    for period in (20, 60, 120):
        if len(closes) >= period:
            ma = sum(closes[-period:]) / period
            parts.append(f'{period}일선 {(now / ma - 1) * 100:+.1f}%')
    if parts:
        lines.append('이동평균 대비  ' + ' · '.join(parts))
    high, low = stock.year_high, stock.year_low
    if high and low:
        lines.append(f'52주 고점 대비 {(now / high - 1) * 100:+.1f}%'
                     f' · 저점 대비 {(now / low - 1) * 100:+.1f}%')
    if len(closes) > 20:
        lines.append(f'최근 20거래일 등락 {(now / closes[-21] - 1) * 100:+.1f}%')
    return '\n'.join(lines) or _EMPTY


def _report_block(target_panel, reports):
    if not target_panel:
        return _EMPTY
    p = target_panel
    lines = [f'최신 목표가 {p["target"]:,}원 ({p["date"]:%y.%m.%d} · {p["provider"]})'
             + (f' · 현재가 대비 {p["gap_now"]:+.1f}%' if p['gap_now'] is not None else '')]
    if p['consensus']:
        line = f'컨센 {p["consensus"]:,}원 (증권사 {p["providers"]}곳)'
        if p['consensus_gap'] is not None:
            line += f' · 이 목표가는 평균 {p["consensus_gap"]:+.1f}%'
        if p['outlier']:
            line += ' [혼자 튐]'
        lines.append(line)
    if p['recent_n']:
        lines.append(f'최근 {p["window"]}일 목표가 방향  '
                     f'상향 {p["up"]} · 유지 {p["flat"]} · 하향 {p["down"]}')
    if reports:
        lines.append('')
        lines.append('최근 리포트')
        for r in reports[:5]:
            target = f'{r.target_price:,}' if r.target_price else '-'
            lines.append(f'  {r.date:%y.%m.%d} {r.provider} {target}'
                         f' {r.recommendation or ""} {r.title}'.rstrip())
    return '\n'.join(lines)


def _how_to_read():
    return '\n'.join([
        f'지분율은 순매수 주식 수를 상장주식수로 나눈 값이다. 금액으로 보면 '
        f'종목 크기에 가려져 큰일인지 알 수 없어 이렇게 본다.',
        '',
        f'{FLOW_LONG_DAYS}일 지분율이 ±{FLOW_STRONG}% 를 넘으면 드문 일이다 '
        f'(관측상 열에 한 번). 그 안쪽은 늘 오가는 수준이라 방향을 논할 값이 '
        f'아니다.',
        '',
        f'[도는 중] 은 {FLOW_LONG_DAYS}일은 순매도인데 {FLOW_SHORT_DAYS}일은 '
        f'순매수라는 뜻이다. [식는 중] 은 그 반대다. 네 번에 한 번쯤 나오며, '
        f'한 기간만 봐서는 안 보이는 신호다.',
        '',
        '외국인과 기관은 대체로 반대로 간다(관측 상관 -0.60). 한쪽만 보고 '
        '판단하면 정반대로 읽는다. 둘의 방향이 같을 때가 드물고 그때 신호가 '
        '가장 세다.',
        '',
        f'공매도 Z 는 오늘 비중이 그 종목의 60일 평소에서 표준편차 몇 개만큼 '
        f'떨어졌는지다. ±{SHORT_Z_STRONG} 를 넘는 날이 열흘에 하루꼴이라 그 '
        f'바깥만 사건으로 본다. 음수는 공매도가 물러났다는 뜻이라 주가에는 '
        f'좋은 소식이다.',
        '',
        '수급 수치는 모두 순매수 "주식 수"다. 금액이 필요하면 종가를 곱해 '
        '추정하되, 그 값을 근거로 삼지는 마라.',
    ])


def build_supply_prompt_vars(stock, dashboard, target_panel, trends_asc,
                             shorts_asc, charts_asc, reports, today):
    """프롬프트 치환용 {변수: 값}. 값이 없으면 '데이터 없음'을 넣는다."""
    shorts_map = {s.date: s for s in shorts_asc}
    charts_map = {c.date: c for c in charts_asc}
    latest = charts_asc[-1] if charts_asc else None

    price = f'{stock.current_price:,}원' if stock.current_price else '-'
    if stock.change_rate is not None:
        price += f' ({stock.change_rate:+}%)'
    if stock.volume_change is not None:
        price += f' · 거래량 전일비 {stock.volume_change:+}%'

    return {
        '{종목명}': stock.name,
        '{종목코드}': stock.code,
        '{오늘날짜}': f'{latest.date:%Y-%m-%d}' if latest else f'{today:%Y-%m-%d}',
        '{현재가}': price,
        '{수급요약}': _supply_summary(dashboard),
        '{공매도요약}': _short_summary(dashboard, shorts_asc),
        '{일별수급}': _daily_table(trends_asc, shorts_map, charts_map, charts_asc),
        '{투자자별}': _investor_breakdown(trends_asc),
        '{주가맥락}': _price_context(charts_asc, stock),
        '{리포트}': _report_block(target_panel, reports),
        '{읽는법}': _how_to_read(),
    }
