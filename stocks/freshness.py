# -*- coding: utf-8 -*-
"""
데이터가 늘어야 할 때 늘었는지 본다.

명령이 실패하면 종료코드로 알린다(docs/commands.md). 그런데 그것으로 못 잡는
고장이 따로 있다 — **명령은 성공했는데 입력이 썩은 경우**다.

  시장 수급이 석 달 끊긴 동안 save_market_indicator 는 외인 20일 누적을
  엉터리로 계산하면서 날마다 '완료' 를 찍었다. 자기 할 일은 다 했기 때문이다.

성공·실패가 아니라 신선도의 문제다. 여기서 보는 것이 그것이다.

── 기준일을 어디서 잡나 ──────────────────────────────────────────────

'오늘 것이 있나' 로 보면 주말·공휴일마다 오작동한다. 그래서 둘을 같이 쓴다.

  ① 상대   일별 데이터들의 최신일 중 가장 최신을 기준 삼아, 거기서 혼자
           뒤처진 것을 찾는다.
  ② 절대   그 기준일 자체가 오늘로부터 너무 멀면 전체가 멈춘 것이다.

①만 있으면 다 같이 멈췄을 때 못 잡고, ②만 있으면 공휴일마다 운다. 둘이
서로의 구멍을 막는다. 연휴가 길면 ②가 오경보를 내는데, 1년에 한두 번이고
그때 한 번 들여다보는 것은 나쁘지 않다.

── 무엇을 보는지는 코드가 선언한다 ────────────────────────────────────

'모든 데이터가 오늘 것이어야 한다' 로 짜면 틀린다.

  MarketDiary   사람이 쓰는 투자일기다. 몇 달 비어도 정상
  WeeklyChart   주 단위다. 금요일 것이 최신인 게 맞다
  Gongsi        부정기다. 며칠 없을 수 있다
  InfoETF       행이 안 늘고 값만 바뀐다. 날짜 칸이 아예 없다

무엇이 언제 늘어야 하는지는 추측할 수 없다. 아래 CHECKS 에 적어 둔다.
"""
from datetime import date, datetime, time, timedelta

from django.db.models import Max

from stocks.models import (DailyAccountSnapshot, DailyChart, DailyChartETF,
                           DailyTradeDiary, Financial, Gongsi, IndexChart,
                           Info, InfoETF, InvestorTrend, MarketIndicator,
                           MarketTrend, Report, Sector, ShortSelling)


class Daily:
    """거래일마다 늘어야 하는 것.

    group 을 주면 그 값마다 따로 본다 — 코스피는 들어왔는데 코스닥만 빠진
    경우가 있다. 합쳐서 보면 '최신일 11-13' 하나로 가려진다.
    """

    def __init__(self, label, model, group=None, field='date', slack=0):
        self.label = label
        self.model = model
        self.group = group
        self.field = field
        # 이 항목만 하루 늦게 들어오는 것이 정상일 때 쓴다. 기본은 0.
        self.slack = slack

    def latest(self):
        """(전체 최신일, {그룹: 최신일})"""
        qs = self.model.objects.all()
        overall = qs.aggregate(Max(self.field))[f'{self.field}__max']
        per_group = {}
        if self.group:
            rows = (qs.values(self.group)
                      .annotate(latest=Max(self.field))
                      .order_by(self.group))
            per_group = {r[self.group]: r['latest'] for r in rows}
        return overall, per_group


# 거래일마다 늘어야 하는 것들.
#
# 여기 없는 것은 일부러 뺀 것이다.
#   MarketDiary              사람이 쓰는 투자일기
#   WeeklyChart/MonthlyChart 주·월 단위라 이 방식으로 볼 수 없다
#   Gongsi/Report/Financial  부정기. 2단계(정체 점검)에서 본다
#   InfoETF                  날짜 칸이 없다. 2단계(교차 검증)에서 본다
CHECKS = [
    Daily('지수 차트', IndexChart, group='code'),
    Daily('시장 수급', MarketTrend, group='market'),
    Daily('시장 지표', MarketIndicator, group='market'),
    Daily('일봉', DailyChart),
    Daily('ETF 일봉', DailyChartETF),
    Daily('업종', Sector),
    Daily('종목 수급', InvestorTrend),
    Daily('공매도', ShortSelling),
    Daily('계좌 스냅샷', DailyAccountSnapshot),
    Daily('매매일지', DailyTradeDiary),
]

class Gap:
    """부정기 데이터. 거래일마다 늘지는 않지만 너무 오래 비면 의심스럽다.

    공시·리포트는 종목에 따라 며칠씩 없을 수 있다. 다만 관심종목이 여든 개가
    넘어 실제로는 거의 날마다 뭔가 들어온다 — 최근 120개 날짜를 재 보니
    간격 중앙값 1일, 최대 5일이었다. 10일을 넘기면 수집이 멈춘 것이다.
    """

    def __init__(self, label, model, days, field='date'):
        self.label = label
        self.model = model
        self.days = days
        self.field = field

    def latest(self):
        value = self.model.objects.aggregate(Max(self.field))[f'{self.field}__max']
        # updated_at 처럼 시각까지 든 칸은 날짜만 떼어 견준다.
        return value.date() if isinstance(value, datetime) else value


class Cross:
    """두 출처가 같은 값을 말하는지 본다.

    날짜 칸이 없는 데이터를 보는 유일한 방법이다. InfoETF 는 행이 늘지 않고
    값만 바뀌는데, 코드가 updated_at 은 매번 갱신하면서 current_price 는
    그대로 두는 바람에 넉 달 동안 겉보기로 멀쩡했다. 차트와 견줬더니 최대
    163% 어긋나 있었다 — 그 비교를 여기에 옮긴다.
    """

    def __init__(self, label, fn):
        self.label = label
        self.fn = fn


def etf_price_vs_chart():
    """ETF 대시보드 현재가 vs 일봉 최신 종가. (어긋난 수, 전체, 보기)"""
    bad, total, examples = 0, 0, []
    for etf in InfoETF.objects.filter(is_active=True):
        chart = DailyChartETF.objects.filter(etf=etf).order_by('-date').first()
        if not chart:
            continue
        total += 1
        if etf.current_price != chart.closing_price:
            bad += 1
            if len(examples) < 3:
                examples.append(f'{etf.code} {etf.name[:12]} '
                                f'{etf.current_price or 0:,} vs {chart.closing_price:,}')
    return bad, total, examples


def stock_price_vs_chart():
    """종목 현재가 vs 일봉 최신 종가. 관심종목만 본다 — 전체가 멈추면
    관심종목도 같이 멈추므로 그것으로 충분하다."""
    bad, total, examples = 0, 0, []
    for stock in Info.objects.filter(interest_level__isnull=False):
        chart = DailyChart.objects.filter(stock=stock).order_by('-date').first()
        if not chart:
            continue
        total += 1
        if stock.current_price != chart.closing_price:
            bad += 1
            if len(examples) < 3:
                examples.append(f'{stock.code} {stock.name[:12]} '
                                f'{stock.current_price or 0:,} vs {chart.closing_price:,}')
    return bad, total, examples


# 부정기 데이터. days 는 달력일이다.
GAPS = [
    Gap('공시', Gongsi, days=10),
    Gap('리포트', Report, days=10),
    # 재무는 주간 배치다. 값이 안 바뀐 행은 건드리지 않으므로 종목 하나만
    # 보면 안 되고, 전체에서 가장 최근에 바뀐 것을 본다. 1,249종목을 훑으면
    # 컨센서스가 움직인 것이 늘 몇 개는 있다.
    Gap('재무', Financial, days=10, field='updated_at'),
]

CROSSES = [
    Cross('ETF 대시보드', etf_price_vs_chart),
    Cross('종목 현재가', stock_price_vs_chart),
]

# 어긋난 비율이 이보다 크면 고장으로 본다.
#
# 한두 종목이 어긋나는 것은 거래정지·상장폐지처럼 늘 있는 일이다. 수집이
# 멈추면 하나가 아니라 전부 어긋난다 — ETF 때도 스물셋이 전부였다.
CROSS_BAD_RATIO = 0.3

# 장중에는 교차 검증을 건너뛴다. 현재가와 전일 종가가 다른 것이 당연해서
# 전부 어긋난 것처럼 보인다. 배치는 저녁에 도니 걸릴 일이 없고, 손으로
# 낮에 돌렸을 때만 해당한다.
MARKET_OPEN = time(9, 0)
MARKET_CLOSE = time(16, 0)


# 기준일이 오늘로부터 이만큼(영업일) 넘게 떨어지면 전체가 멈춘 것으로 본다.
# 설·추석 연휴가 이보다 길면 오경보가 난다 — 1년에 한두 번이다.
MAX_LAG_BUSINESS_DAYS = 3


def business_days_between(start, end):
    """start 다음날부터 end 까지의 평일 수. 공휴일은 세지 않는다.

    공휴일표가 없어 평일로만 센다. 그만큼 실제보다 크게 나오므로 경보가
    조금 이르게 울린다 — 늦게 우는 것보다 낫다.
    """
    if not start or not end or start >= end:
        return 0
    days = 0
    cur = start + timedelta(days=1)
    while cur <= end:
        if cur.weekday() < 5:
            days += 1
        cur += timedelta(days=1)
    return days


def is_market_hours(now=None):
    now = now or datetime.now()
    return now.weekday() < 5 and MARKET_OPEN <= now.time() <= MARKET_CLOSE


def run(today=None, now=None):
    """전부 훑는다. (기준일, 문제목록, 현황목록)

    문제목록의 각 항목은 사람이 읽을 한 줄이다.
    현황목록은 이상이 없어도 로그에 남길 표다.
    """
    today = today or date.today()

    status = []       # (라벨, 최신일, 뒤처짐, 비고)
    latest_dates = []

    for check in CHECKS:
        overall, per_group = check.latest()
        status.append({'check': check, 'overall': overall, 'groups': per_group})
        if overall:
            latest_dates.append(overall)

    if not latest_dates:
        return None, ['볼 데이터가 하나도 없습니다 (DB 가 비었거나 모델이 바뀌었습니다)'], status

    # ① 기준일 — 가장 앞선 놈. 이게 '마지막 거래일' 노릇을 한다.
    reference = max(latest_dates)

    problems = []

    # ② 절대 — 기준일 자체가 멀면 전체가 멈춘 것이다.
    lag = business_days_between(reference, today)
    if lag > MAX_LAG_BUSINESS_DAYS:
        problems.append(
            f'전체 정지: 가장 최신인 데이터도 {reference} 다 '
            f'(오늘 {today} 기준 {lag}영업일 전). 배치가 아예 안 돌고 있거나 '
            f'연휴입니다'
        )

    # ③ 상대 — 기준일에서 혼자 뒤처진 놈을 찾는다.
    for s in status:
        check, overall, groups = s['check'], s['overall'], s['groups']

        if overall is None:
            problems.append(f'{check.label}: 데이터가 한 건도 없습니다')
            s['behind'] = None
            continue

        behind = business_days_between(overall, reference)
        s['behind'] = behind
        if behind > check.slack:
            problems.append(
                f'{check.label}: {behind}영업일 뒤처짐 '
                f'(최신 {overall}, 기준 {reference})'
            )
            continue

        # 그룹을 따로 본다. 코스피는 들어왔는데 코스닥만 빠진 경우가 있다.
        for name, g_latest in sorted(groups.items()):
            g_behind = business_days_between(g_latest, reference)
            if g_behind > check.slack:
                problems.append(
                    f'{check.label}[{name}]: {g_behind}영업일 뒤처짐 '
                    f'(최신 {g_latest}, 기준 {reference})'
                )

    # ④ 정체 — 부정기 데이터. 달력일로 센다. 거래일마다 늘지 않으므로
    #    기준일과 견주는 ③ 방식을 쓸 수 없다.
    for gap in GAPS:
        latest = gap.latest()
        if latest is None:
            problems.append(f'{gap.label}: 데이터가 한 건도 없습니다')
            status.append({'label': gap.label, 'overall': None, 'note': '데이터 없음'})
            continue
        days = (today - latest).days
        status.append({'label': gap.label, 'overall': latest,
                       'note': f'{days}일 전' if days else '오늘'})
        if days > gap.days:
            problems.append(
                f'{gap.label}: {days}일째 새로 들어온 것이 없습니다 '
                f'(최신 {latest}, 한도 {gap.days}일)'
            )

    # ⑤ 교차 검증 — 두 출처가 어긋나는지. 날짜 칸이 없는 데이터를 보는
    #    유일한 방법이다.
    if is_market_hours(now):
        status.append({'label': '교차 검증', 'overall': None,
                       'note': '장중이라 건너뜀'})
    else:
        for cross in CROSSES:
            bad, total, examples = cross.fn()
            status.append({'label': cross.label, 'overall': None,
                           'note': f'{bad}/{total} 어긋남' if total else '볼 것 없음'})
            if total and bad / total > CROSS_BAD_RATIO:
                detail = ' · '.join(examples)
                problems.append(
                    f'{cross.label}: {total}개 중 {bad}개가 차트와 어긋납니다. {detail}'
                )

    return reference, problems, status
