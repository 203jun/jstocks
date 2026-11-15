# -*- coding: utf-8 -*-
import time
import requests
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand, CommandError
from stocks.models import MarketTrend
from stocks.logger import StockLogger


class FetchFailed(Exception):
    """못 받았다. '받을 것이 없다' 와 다른 일이다."""


class Command(BaseCommand):
    help = '''
시장별 투자자 매매동향 저장 (네이버)

옵션:
  --market    (선택) KOSPI / KOSDAQ / all (기본값: all)
  --mode      (선택) all (60영업일) / last (최근 1영업일, 기본값)
  --days      (선택) 받아올 영업일 수. 지정하면 --mode 보다 우선
  --clear     (선택) 전체 데이터 삭제
  --log-level (선택) debug / info / warning / error (기본값: info)

예시:
  python manage.py save_market_trend
  python manage.py save_market_trend --market KOSPI --mode all
  python manage.py save_market_trend --days 250      # 과거 백필 (약 1년)
  python manage.py save_market_trend --clear
'''

    # 네이버 지수 심볼. 선물(FUT)은 쓰지 않는다 — 보는 화면이 없다.
    MARKETS = ['KOSPI', 'KOSDAQ']

    # 예전에는 finance.naver.com 의 투자자별 매매동향 화면을 긁었다. 네이버가
    # 그 주소를 410 으로 내리면서 수급이 끊겼다. 지금은 지수 화면이 쓰는 JSON 을
    # 쓴다 — 날짜를 주면 그날 값을 돌려준다.
    #
    # 과거 DB 값과 대조해 보니 코스피·코스닥 20일이 전부 같았다. 같은 출처라
    # 예전 데이터와 그대로 이어지고 단위 변환도 필요 없다 (억원).
    API = 'https://m.stock.naver.com/api/index/{market}/trend'

    HEADERS = {
        'User-Agent': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                       'AppleWebKit/537.36'),
        'Referer': 'https://m.stock.naver.com/',
        'Accept': 'application/json',
    }

    def add_arguments(self, parser):
        parser.add_argument('--market', type=str, default='all',
                            help='KOSPI, KOSDAQ, all (기본값: all)')
        parser.add_argument('--mode', type=str, default='last',
                            choices=['all', 'last'],
                            help='all: 60영업일, last: 최근 1영업일 (기본값: last)')
        parser.add_argument('--days', type=int, default=None,
                            help='받아올 영업일 수. 지정하면 --mode 보다 우선')
        parser.add_argument('--clear', action='store_true', help='전체 데이터 삭제')
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        if options.get('clear'):
            deleted, _ = MarketTrend.objects.all().delete()
            self.stdout.write(self.style.SUCCESS(f'MarketTrend 데이터 {deleted}건 삭제 완료'))
            return

        self.log = StockLogger(self.stdout, self.style, options, 'save_market_trend')

        market = options['market'].upper()
        days = options['days'] if options['days'] is not None else (60 if options['mode'] == 'all' else 1)
        if days < 1:
            self.log.error(f'--days 는 1 이상이어야 합니다: {days}')
            return

        if market == 'ALL':
            markets = list(self.MARKETS)
        elif market in self.MARKETS:
            markets = [market]
        else:
            self.log.error(f'지원하지 않는 시장: {market}')
            self.log.info(f'지원: {", ".join(self.MARKETS)}')
            return

        self.log.info(f'시장 투자동향 저장 시작 (대상: {", ".join(markets)}, {days}영업일)')

        total_created = total_updated = 0
        all_errors = []

        for market_name in markets:
            created, updated, errors = self.process_market(market_name, days)
            total_created += created
            total_updated += updated
            all_errors.extend(errors)

        self.log.separator()
        # '오류: N개' 는 열다섯 개 명령이 끝에 찍는 공통 관례다. 날마다 도는
        # 스크립트가 이 줄을 보고 텔레그램에 실어 보낸다 (batch_lib.sh).
        if all_errors:
            self.log.info(f'완료 | 신규: {total_created}개, 업데이트: {total_updated}개, '
                          f'오류: {len(all_errors)}개', success=True)
            self.log.info('')
            self.log.info('[오류 목록]')
            for e in all_errors:
                self.log.error(f'  {e}')
        else:
            self.log.info(f'완료 | 신규: {total_created}개, 업데이트: {total_updated}개', success=True)

        # 한 행도 못 받았으면 비정상 종료로 끝낸다. 로그만 찍고 0 으로 끝나면
        # 배치가 '완료' 를 보낸다 — 예전에 그래서 넉 달을 모르고 지나갔다.
        if all_errors and total_created == 0 and total_updated == 0:
            raise CommandError(
                f'시장 투자동향을 한 행도 받지 못했습니다 ({", ".join(markets)}). '
                '네이버가 주소를 내렸거나 응답 모양이 바뀐 것으로 봐야 합니다.'
            )

    def process_market(self, market_name, days):
        """날짜를 거꾸로 훑어 days 영업일을 채운다. (신규, 수정, 오류목록)"""
        self.log.separator()
        self.log.info(f'[{market_name}] 처리 시작')

        created = updated = 0
        errors = []
        collected = 0
        holidays = 0

        # 영업일이 몇 날 전인지 모르므로 달력일을 거꾸로 걷는다. 주말·휴장일은
        # 값이 0 으로 오므로 건너뛴다. 영업일 하나에 달력일 하나를 넘게 쓰는
        # 셈이라 넉넉히 돈다 (days 의 두 배 + 10).
        day = datetime.now().date()
        limit = days * 2 + 10

        for _ in range(limit):
            if collected >= days:
                break
            bizdate = day.strftime('%Y%m%d')
            day -= timedelta(days=1)

            try:
                row = self.fetch_day(market_name, bizdate)
            except FetchFailed as e:
                self.log.error(f'  [{market_name}] {bizdate} 조회 실패: {e}')
                errors.append(f'{market_name} {bizdate}: {e}')
                break

            if row is None:
                holidays += 1
                self.log.debug(f'  {bizdate} 휴장 (값이 전부 0)')
                time.sleep(0.2)
                continue

            c, u = self.save_day(market_name, row)
            created += c
            updated += u
            collected += 1
            self.log.debug(f'  {bizdate} 개인 {row["individual"]:,} '
                           f'외국인 {row["foreign"]:,} 기관 {row["institution"]:,}')
            time.sleep(0.2)

        if collected:
            self.log.info(f'[{market_name}] {collected}영업일 수집 (휴장 {holidays}일 건너뜀) '
                          f'| 신규 {created}, 업데이트 {updated}')
        elif errors:
            self.log.error(f'[{market_name}] 조회 실패로 한 행도 받지 못했습니다')
        else:
            self.log.info(f'[{market_name}] 데이터 없음')

        return created, updated, errors

    def fetch_day(self, market_name, bizdate):
        """하루치. 휴장일이면 None.

        응답은 이렇게 온다 (부호와 천 단위 쉼표가 글자로 들어 있다).
            {"bizdate":"20261113","personalValue":"+145",
             "foreignValue":"-5,419","institutionalValue":"-59"}

        휴장일·미래 날짜에도 200 을 주면서 값만 "0" 으로 돌려준다. 그대로
        저장하면 쉬는 날이 '순매수 0' 으로 남는다.
        """
        url = self.API.format(market=market_name)
        try:
            r = requests.get(url, params={'bizdate': bizdate},
                             headers=self.HEADERS, timeout=10)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            raise FetchFailed(str(e)) from e

        try:
            individual = self.parse_number(data['personalValue'])
            foreign = self.parse_number(data['foreignValue'])
            institution = self.parse_number(data['institutionalValue'])
        except (KeyError, TypeError, ValueError) as e:
            # 응답 모양이 바뀌면 조용히 0 으로 떨어지지 않게 실패로 올린다.
            raise FetchFailed(f'응답 모양이 다르다 ({e}): {str(data)[:120]}') from e

        if individual == 0 and foreign == 0 and institution == 0:
            return None

        return {
            'date': datetime.strptime(data.get('bizdate') or bizdate, '%Y%m%d').date(),
            'individual': individual,
            'foreign': foreign,
            'institution': institution,
        }

    def save_day(self, market_name, row):
        """같은 날은 덮어쓴다. (신규, 수정)"""
        _, created = MarketTrend.objects.update_or_create(
            market=market_name,
            date=row['date'],
            defaults={
                'individual': row['individual'],
                'foreign': row['foreign'],
                'institution': row['institution'],
            },
        )
        return (1, 0) if created else (0, 1)

    def parse_number(self, text):
        """'+145' · '-5,419' · '0' -> int"""
        if text is None:
            raise ValueError('값이 없다')
        s = str(text).replace(',', '').replace('+', '').strip()
        if s in ('', '-'):
            return 0
        return int(s)
