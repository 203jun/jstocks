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
from datetime import date, timedelta

from django.db.models import Max

from stocks.models import (DailyAccountSnapshot, DailyChart, DailyChartETF,
                           DailyTradeDiary, IndexChart, InvestorTrend,
                           MarketIndicator, MarketTrend, Sector, ShortSelling)


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


def run(today=None):
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

    return reference, problems, status
