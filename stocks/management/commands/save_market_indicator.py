# -*- coding: utf-8 -*-
import bisect
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from django.core.management.base import BaseCommand

from stocks.logger import StockLogger
from stocks.market_adr import fetch_adr, AdrFetchError
from stocks.models import IndexChart, MarketIndicator, MarketTrend


class Command(BaseCommand):
    help = '''
시장 일일 지표 저장 (KOSPI, KOSDAQ)

4개 지표를 하루 한 행으로 계산해 MarketIndicator 에 저장한다.
  1. 이격도(20일)  = 종가 / 20일 이평 * 100
  2. ADR           = adrinfo.kr 수집값
  3. 외국인 20일 누적 순매수 = MarketTrend 최근 20영업일 합
  4. 200일선 대비  = (종가 / 200일 이평 - 1) * 100

옵션:
  --market    (선택) KOSPI / KOSDAQ / all (기본값: all)
  --mode      (선택) all (전체 재계산) / last (최근 10영업일, 기본값)
  --from      (선택) YYYY-MM-DD 이후만 계산 (--mode all 과 함께)
  --dry-run   (선택) 저장하지 않고 계산 결과만 출력
  --clear     (선택) 전체 데이터 삭제
  --log-level (선택) debug / info / error (기본값: info)

예시:
  python manage.py save_market_indicator                    # 일일 배치
  python manage.py save_market_indicator --mode all         # 최초 적재/재계산
  python manage.py save_market_indicator --mode all --dry-run
'''

    MARKETS = ['KOSPI', 'KOSDAQ']

    MA_SHORT = 20          # 이격도 기준
    MA_LONG = 200          # 레짐 판단 기준
    FOREIGN_WINDOW = 20    # 외국인 누적 순매수 영업일 수
    LAST_MODE_DAYS = 10    # --mode last 에서 다시 계산할 영업일 수

    # 매매동향이 지수보다 뒤처져 있으면 오래된 합계를 그럴듯하게 저장하게 된다.
    # 지수 날짜와 이만큼 이상 벌어지면 수급은 비워 둔다.
    MAX_TREND_LAG_DAYS = 5

    def add_arguments(self, parser):
        parser.add_argument('--market', type=str, default='all',
                            help='Market: KOSPI, KOSDAQ, all (default: all)')
        parser.add_argument('--mode', type=str, default='last', choices=['all', 'last'],
                            help='all: 전체 재계산, last: 최근 10영업일 (default: last)')
        parser.add_argument('--from', dest='from_date', type=str, default=None,
                            help='YYYY-MM-DD 이후만 계산')
        parser.add_argument('--dry-run', action='store_true',
                            help='저장하지 않고 계산 결과만 출력')
        parser.add_argument('--clear', action='store_true',
                            help='전체 데이터 삭제')
        StockLogger.add_arguments(parser)

    # ------------------------------------------------------------------ #

    def handle(self, *args, **options):
        if options.get('clear'):
            deleted, _ = MarketIndicator.objects.all().delete()
            self.stdout.write(self.style.SUCCESS(f'MarketIndicator 데이터 {deleted}건 삭제 완료'))
            return

        self.log = StockLogger(self.stdout, self.style, options, 'save_market_indicator')

        market_opt = options['market'].upper()
        if market_opt == 'ALL':
            markets = list(self.MARKETS)
        elif market_opt in self.MARKETS:
            markets = [market_opt]
        else:
            self.log.error(f'지원하지 않는 시장: {market_opt} (가능: {", ".join(self.MARKETS)})')
            return

        from_date = None
        if options['from_date']:
            try:
                from_date = datetime.strptime(options['from_date'], '%Y-%m-%d').date()
            except ValueError:
                self.log.error(f'--from 형식이 잘못됐습니다: {options["from_date"]} (YYYY-MM-DD)')
                return

        mode = options['mode']
        dry_run = options['dry_run']

        # ADR 은 한 번 호출로 전 기간이 오므로 시장 루프 밖에서 받는다
        self.log.info('ADR 수집 중 (adrinfo.kr)...')
        try:
            adr_all = fetch_adr()
        except AdrFetchError as exc:
            self.log.error(f'ADR 수집 실패: {exc}')
            return
        for market in markets:
            series = adr_all.get(market, {})
            self.log.debug(f'  {market} ADR {len(series)}건')

        self.log.info(
            f'시장 지표 계산 시작 (모드: {mode}, 대상: {", ".join(markets)})'
            + (' [dry-run]' if dry_run else '')
        )

        total_created = total_updated = 0
        for market in markets:
            created, updated = self.process_market(
                market, adr_all.get(market, {}), mode, from_date, dry_run
            )
            total_created += created
            total_updated += updated

        self.log.separator()
        if dry_run:
            self.log.info('완료 [dry-run] — 저장하지 않았습니다', success=True)
        else:
            self.log.info(f'완료 | 신규: {total_created}건, 업데이트: {total_updated}건', success=True)

    # ------------------------------------------------------------------ #

    def process_market(self, market, adr_series, mode, from_date, dry_run):
        self.log.separator()
        self.log.info(f'[{market}] 처리 시작')

        charts = list(
            IndexChart.objects.filter(code=market).order_by('date').values_list('date', 'closing_price')
        )
        if not charts:
            self.log.error(f'[{market}] IndexChart 데이터가 없습니다')
            return 0, 0

        dates = [row[0] for row in charts]
        closes = [Decimal(row[1]) for row in charts]

        trend_map = dict(
            MarketTrend.objects.filter(market=market).values_list('date', 'foreign')
        )
        trend_dates = sorted(trend_map)

        # 계산 대상 인덱스 정하기
        targets = range(len(dates))
        if mode == 'last':
            targets = range(max(0, len(dates) - self.LAST_MODE_DAYS), len(dates))
        if from_date:
            start = bisect.bisect_left(dates, from_date)
            targets = range(max(targets.start, start), targets.stop)

        rows = [
            self.build_row(market, i, dates, closes, trend_map, trend_dates, adr_series)
            for i in targets
        ]
        self.log.info(f'[{market}] 계산 대상 {len(rows)}일 ({dates[targets.start]} ~ {dates[-1]})')

        missing = {
            'ADR': sum(1 for r in rows if r['adr'] is None),
            '이격도': sum(1 for r in rows if r['disparity'] is None),
            '수급': sum(1 for r in rows if r['foreign_net_20d'] is None),
            '200일선': sum(1 for r in rows if r['ma200_gap'] is None),
        }
        if any(missing.values()):
            detail = ', '.join(f'{k} {v}일' for k, v in missing.items() if v)
            self.log.info(f'[{market}] 이력 부족으로 비어 있는 값: {detail}')

        self.print_sample(market, rows)

        if dry_run:
            return 0, 0

        created = updated = 0
        for row in rows:
            _, is_created = MarketIndicator.objects.update_or_create(
                market=market, date=row['date'],
                defaults={k: v for k, v in row.items() if k != 'date'},
            )
            created += is_created
            updated += (not is_created)

        self.log.info(f'[{market}] 저장 완료 | 신규 {created}건, 업데이트 {updated}건')
        return created, updated

    # ------------------------------------------------------------------ #

    def build_row(self, market, i, dates, closes, trend_map, trend_dates, adr_series):
        """i번째 거래일의 지표 한 행을 만든다"""
        date = dates[i]
        close = closes[i]

        ma20 = self.moving_average(closes, i, self.MA_SHORT)
        ma200 = self.moving_average(closes, i, self.MA_LONG)

        return {
            'date': date,
            'close': self.q(close),
            'ma20': self.q(ma20),
            'disparity': self.q(close / ma20 * 100) if ma20 else None,
            'adr': self.q(adr_series.get(date)),
            'foreign_net_20d': self.foreign_net(date, trend_map, trend_dates),
            'ma200': self.q(ma200),
            'ma200_gap': self.q((close / ma200 - 1) * 100) if ma200 else None,
        }

    def moving_average(self, closes, i, period):
        """i번째까지 period일 이동평균. 이력이 모자라면 None."""
        if i + 1 < period:
            return None
        window = closes[i + 1 - period:i + 1]
        return sum(window) / period

    def foreign_net(self, date, trend_map, trend_dates):
        """해당 일자까지의 외국인 20영업일 누적 순매수 (백만원). 부족하거나 오래됐으면 None."""
        end = bisect.bisect_right(trend_dates, date)
        if end < self.FOREIGN_WINDOW:
            return None
        window = trend_dates[end - self.FOREIGN_WINDOW:end]
        # 매매동향이 지수보다 한참 뒤처졌으면 오래된 합계를 저장하지 않는다
        if (date - window[-1]).days > self.MAX_TREND_LAG_DAYS:
            return None
        return sum(trend_map[d] for d in window)

    @staticmethod
    def q(value):
        """소수점 2자리로 반올림 (None 은 그대로)"""
        if value is None:
            return None
        return Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    def print_sample(self, market, rows):
        """가장 최근 3일치를 표로 찍어 눈으로 확인할 수 있게 한다"""
        if not rows:
            return
        fmt = lambda v: '-' if v is None else f'{v:,}'
        self.log.info(
            f'  {"일자":<12}{"종가":>11}{"이격도":>9}{"ADR":>8}{"외인20일":>13}{"200일선":>10}'
        )
        for row in rows[-3:]:
            foreign = row['foreign_net_20d']
            foreign_txt = '-' if foreign is None else f'{foreign / 100:,.0f}억'
            gap = row['ma200_gap']
            gap_txt = '-' if gap is None else f'{gap:+.2f}%'
            self.log.info(
                f'  {str(row["date"]):<12}{fmt(row["close"]):>11}{fmt(row["disparity"]):>9}'
                f'{fmt(row["adr"]):>8}{foreign_txt:>13}{gap_txt:>10}'
            )
