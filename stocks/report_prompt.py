# -*- coding: utf-8 -*-
"""
애널리스트 리포트를 놓고 매매 참고를 묻는 프롬프트의 입력값.

세 탭 중 여기만 1차 자료가 없다. 리포트 원문(PDF)을 받아올 수 없어서
제목·증권사·목표가·투자의견만 있다. 본문은 AI 가 웹에서 찾아야 한다.

그래서 검색이 실패해도 판단이 무너지지 않게 짠다. 진짜 재료는 원문이
아니라 이미 숫자에 있다 — 목표가 방향(상향/하향), 목표가가 갈리는 폭,
발행 시점 괴리율, 목표가 추이와 주가 추이의 어긋남. 검색은 '왜'를
채우는 보조다.
"""
import re
from collections import defaultdict
from datetime import timedelta

from .report_signal import CONSENSUS_OUTLIER, CYCLE_DAYS, GAP_STRONG, GAP_THIN
from .supply_prompt import _price_context

# 목록에 넣을 창과 건수. 증권사별 최신 1건으로 걸러도 25곳이 나온다.
# 전부 넣어도 분포는 최고·최저·컨센 세 숫자로 이미 보이고, 검색 대상만
# 흐려진다.
REPORT_WINDOW_DAYS = 180
REPORT_MAX_ROWS = 12

# 목표가 추이에 보여줄 날짜 수
TREND_DAYS = 10

_EMPTY = '데이터 없음'

REPORT_VARIABLES = [
    ('{종목명}', ''),
    ('{종목코드}', ''),
    ('{기준일}', '데이터가 계산된 마지막 거래일'),
    ('{오늘날짜}', '오늘 날짜'),
    ('{현재가}', '현재가 · 등락률 · 거래량 전일비'),
    ('{목표가요약}', '최신 목표가 · 괴리율 · 컨센 · 방향 — 여러 줄'),
    ('{리포트목록}', '증권사별 최신 1건, 최근 180일 — 여러 줄'),
    ('{목표가추이}', '날짜별 평균·범위와 그날 종가 — 여러 줄'),
    ('{컨센서스}', '실적 추정치. 없는 종목이 있다 — 여러 줄'),
    ('{주가맥락}', '이동평균 대비 · 52주 고저 대비 — 여러 줄'),
    ('{읽는법}', '임계값과 해석 규칙 (코드에서 자동 생성) — 여러 줄'),
]


def _target_summary(panel):
    if not panel:
        return _EMPTY
    p = panel
    lines = [f'최신 목표가 {p["target"]:,}원 ({p["date"]:%y.%m.%d} · {p["provider"]})'
             + (f' · 현재가 대비 {p["gap_now"]:+.1f}%' if p['gap_now'] is not None else '')]
    if p['gap_issued'] is not None:
        line = f'발행시 괴리율 {p["gap_issued"]:+.1f}%'
        if p['price_move'] is not None:
            line += f' · 그 뒤 주가 {p["price_move"]:+.1f}%'
        lines.append(line)
    if p['consensus']:
        line = f'컨센 {p["consensus"]:,}원 (증권사 {p["providers"]}곳)'
        if p['consensus_gap'] is not None:
            line += f' · 이 목표가는 평균 {p["consensus_gap"]:+.1f}%'
        if p['outlier']:
            line += ' [혼자 튐]'
        lines.append(line)
    lines.append(f'최근 {p["window"]}일 목표가 방향  '
                 f'상향 {p["up"]} · 유지 {p["flat"]} · 하향 {p["down"]}')
    lines.append(f'(리포트 총 {p["total"]}건 · 최근 {p["window"]}일 {p["recent_n"]}건)')
    return '\n'.join(lines)


def _report_rows(reports, today):
    """증권사별 최신 1건. 같은 곳이 네 번 나오면 컨센이 아니라 한 목소리의 반복이다."""
    cut = today - timedelta(days=REPORT_WINDOW_DAYS)
    window = [r for r in reports if r.date and r.date >= cut]
    if not window:
        return _EMPTY

    seen, picked = set(), []
    for r in window:
        if r.provider in seen:
            continue
        seen.add(r.provider)
        picked.append(r)
        if len(picked) >= REPORT_MAX_ROWS:
            break

    lines = []
    for r in picked:
        target = f'{r.target_price:,}' if r.target_price else '-'
        title = re.sub(r'\s+', ' ', r.title or '').strip()
        lines.append(f'  {r.date:%y.%m.%d} {r.provider} {target} '
                     f'{r.recommendation or ""} {title}'.rstrip())
    providers = len({r.provider for r in window})
    lines.append(f'  ({REPORT_WINDOW_DAYS}일 리포트 {len(window)}건 · 증권사 {providers}곳)')
    return '\n'.join(lines)


def _target_trend(reports, closes, today):
    """
    날짜별 목표가 평균과 범위, 그날 종가.

    건수를 같이 적는 이유: 1~2건짜리 날의 평균은 그 증권사의 개별 시각이지
    컨센 변화가 아니다. 적어주지 않으면 '목표가 급락'으로 읽는다.
    """
    cut = today - timedelta(days=REPORT_WINDOW_DAYS)
    by_date = defaultdict(list)
    for r in reports:
        if r.date and r.date >= cut and r.target_price:
            by_date[r.date].append(r.target_price)
    if not by_date:
        return _EMPTY

    lines = []
    for date in sorted(by_date)[-TREND_DAYS:]:
        values = by_date[date]
        avg = sum(values) // len(values)
        span = (f'{min(values):,}~{max(values):,}'
                if min(values) != max(values) else '-')
        close = closes.get(date)
        line = f'  {date:%y.%m.%d}  평균 {avg:,} ({len(values)}건)  범위 {span}'
        if close:
            line += f'  종가 {close:,}'
        lines.append(line)
    return '\n'.join(lines)


def _consensus(rows):
    """실적 추정치. 없는 종목이 많아 그때는 그렇다고 적는다."""
    if not rows:
        return _EMPTY
    lines = []
    for c in rows:
        period = c.quarter or '연간'
        parts = []
        for label, value in (('매출', c.revenue), ('영익', c.operating_profit),
                             ('EPS', c.eps), ('PER', c.per), ('ROE', c.roe)):
            if value is not None:
                parts.append(f'{label} {value:,}')
        if parts:
            lines.append(f'  {c.year} {period:<4} ' + ' · '.join(parts)
                         + (' (추정)' if c.is_estimated else ''))
    return '\n'.join(lines) or _EMPTY


def _how_to_read():
    return '\n'.join([
        '목표가 괴리율은 목표가 ÷ 현재가 - 100 이다. 한국 리포트는 관행적으로 '
        '목표가를 주가보다 30% 남짓 위에 잡는다. 보유 종목 2,045건을 재보니 '
        f'중앙값 +28.4%, 절반이 +21~39% 안에 들어왔다. 그 구간의 숫자는 종목이 '
        f'아니라 증권사 관행을 말하므로 읽어봐야 얻을 것이 없다. 드문 것은 '
        f'+{GAP_STRONG:g}% 이상(상위 10%)과 +{GAP_THIN:g}% 이하(5.8%)다.',
        '',
        '괴리율이 크다는 것만으로 저평가로 읽지 마라. 목표가는 주가에 후행해서 '
        '주가가 빠지면 저절로 커진다. 발행시 괴리율과 그 뒤 주가 등락을 같이 '
        '보면 어느 쪽이 움직여 생긴 간격인지 알 수 있다.',
        '',
        f'컨센은 최근 {CYCLE_DAYS}일에 나온 리포트 중 증권사별 최신 목표가 '
        f'하나씩만 골라 평균 낸 값이다. 창 안의 리포트를 전부 평균하면 상향 '
        f'사이클에서 몇 달 전의 낮은 목표가가 평균을 끌어내려, 의견 차이가 '
        f'아니라 시차를 재게 된다. 이 컨센에서 {CONSENSUS_OUTLIER}% 넘게 '
        f'벗어나면 [혼자 튐]이 붙는다 — 한 명만 튀는 목표가는 노이즈에 가깝다.',
        '',
        f'목표가 방향(상향/유지/하향)은 최근 {CYCLE_DAYS}일 리포트를 같은 '
        f'증권사의 직전 목표가와 견줘 센다. 증권사마다 목표가를 잡는 수준이 '
        f'달라 남과 비교하면 방향이 아니라 시각차가 나온다. 괴리율 자체보다 '
        f'이 방향이 강한 신호다.',
        '',
        '투자의견은 거의 모두 매수다. 관측한 2,071건 중 매수 97.2%, 중립 2.6%, '
        '매도 0건이다. 의견란 자체에는 정보가 없고, 목표가를 주가 근처로 '
        '내리는 것이 사실상의 매도 신호다.',
        '',
        '[목표가 추이]의 날짜별 평균은 그날 발행 건수가 1~2건이면 그 증권사의 '
        '개별 시각일 뿐 컨센 변화가 아니다. 건수를 확인하고 읽어라.',
        '',
        '[컨센서스]의 추정치는 목표가의 근거가 되는 실적 전망이다. 목표가 '
        '방향과 추정 실적의 방향이 어긋나면(상향 사이클인데 적자 추정 등) 그 '
        '간극 자체가 논쟁의 핵심이다. "데이터 없음"이면 언급을 생략하라.',
    ])


def build_report_prompt_vars(stock, target_panel, reports, consensus_rows,
                             charts_asc, today):
    """리포트 탭 프롬프트의 입력값."""
    latest = charts_asc[-1] if charts_asc else None
    closes = {c.date: c.closing_price for c in charts_asc}

    price = f'{stock.current_price:,}원' if stock.current_price else '-'
    if stock.change_rate is not None:
        price += f' ({stock.change_rate:+}%)'
    if stock.volume_change is not None:
        price += f' · 거래량 전일비 {stock.volume_change:+}%'

    return {
        '{종목명}': stock.name,
        '{종목코드}': stock.code,
        '{기준일}': f'{latest.date:%Y-%m-%d}' if latest else f'{today:%Y-%m-%d}',
        '{오늘날짜}': f'{today:%Y-%m-%d}',
        '{현재가}': price,
        '{목표가요약}': _target_summary(target_panel),
        '{리포트목록}': _report_rows(reports, today),
        '{목표가추이}': _target_trend(reports, closes, today),
        '{컨센서스}': _consensus(consensus_rows),
        '{주가맥락}': _price_context(charts_asc, stock),
        '{읽는법}': _how_to_read(),
    }
