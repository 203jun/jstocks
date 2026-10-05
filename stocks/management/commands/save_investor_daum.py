import time
import requests
from datetime import datetime
from django.core.management.base import BaseCommand
from stocks.models import FAV_FILTER, Info, InvestorTrend
from stocks.logger import StockLogger

# --mode last 가 받아오는 날수. 하루만 받으면 늦게 올라온 날을 영구히 놓친다.
LAST_MODE_DAYS = 5


class Command(BaseCommand):
    help = '''
다음 금융 투자자별 매매동향 저장 (외국인/기관 순매수량)

옵션:
  --code      (필수) 종목코드 또는 "all" / "fav"
              - all: 전체 종목
              - fav: 관심 종목만 (interest_level 설정된 종목)
  --mode      (필수) all (최근 60일) / last (최근 1일)
  --log-level (선택) debug / info / warning / error (기본값: info)

예시:
  python manage.py save_investor_daum --code 204620 --mode last
  python manage.py save_investor_daum --code 005930 --mode all
  python manage.py save_investor_daum --code all --mode last
  python manage.py save_investor_daum --code fav --mode last
'''

    def add_arguments(self, parser):
        parser.add_argument(
            '--code',
            type=str,
            help='종목코드 또는 "all" / "fav"'
        )
        parser.add_argument(
            '--mode',
            type=str,
            choices=['all', 'last'],
            help='조회 모드: all(최근 60일), last(최근 1일)'
        )
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        if not options.get('code') or not options.get('mode'):
            self.print_help('manage.py', 'save_investor_daum')
            return

        self.log = StockLogger(self.stdout, self.style, options, 'save_investor_daum')

        code = options['code']
        mode = options['mode']

        # 전체/관심 종목 처리
        if code.lower() in ['all', 'fav']:
            stocks = Info.objects.filter(is_active=True)

            if code.lower() == 'fav':
                stocks = stocks.filter(FAV_FILTER)
                target_name = '관심 종목'
            else:
                target_name = '전체 종목'

            stocks = stocks.order_by('code')
            total = stocks.count()

            self.log.info(f'다음 금융 투자자 매매동향 저장 시작 (모드: {mode}, 대상: {target_name} {total}개)')

            total_updated = 0
            error_list = []

            for idx, stock in enumerate(stocks, start=1):
                try:
                    data = self.fetch_investor_data(stock.code, mode)
                    if data:
                        updated = self.save_to_db(stock, data)
                        total_updated += updated
                        self.log.info(f'[{idx}/{total}] {stock.code} {stock.name}: {updated}건 저장')
                    else:
                        self.log.warning(f'[{idx}/{total}] {stock.code} {stock.name}: 데이터 없음')
                except Exception as e:
                    self.log.error(f'[{idx}/{total}] {stock.code} {stock.name}: 실패 - {str(e)}')
                    error_list.append((stock.code, stock.name, str(e)))

                if idx < total:
                    time.sleep(0.3)

            self.log.separator()
            if error_list:
                self.log.info(f'완료 | 저장: {total_updated}건, 오류: {len(error_list)}개', success=True)
            else:
                self.log.info(f'완료 | 저장: {total_updated}건', success=True)

        # 단일 종목 처리
        else:
            try:
                stock = Info.objects.get(code=code)
            except Info.DoesNotExist:
                self.log.error(f'종목 정보 없음: {code}')
                return

            self.log.info(f'종목: {stock.name}({code}) | 모드: {mode}')
            self.log.separator()

            data = self.fetch_investor_data(code, mode)
            if data:
                updated = self.save_to_db(stock, data)
                self.log.info(f'저장 완료: {updated}건', success=True)
                self.print_data(data[:5])
            else:
                self.log.warning('데이터 없음')

    def fetch_investor_data(self, stock_code, mode):
        """다음 금융 API에서 투자자별 매매동향 조회"""
        symbol = f'A{stock_code}' if not stock_code.startswith('A') else stock_code

        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Referer': f'https://finance.daum.net/quotes/{symbol}',
        }

        # last 는 '최근 1일' 이 아니라 '최근 며칠' 이다.
        #
        # 한 건만 받으면, 다음 금융이 그날 수급을 저녁 늦게 올리는 날에는 전날
        # 것을 받고 끝난다. 그날 칸은 비어 있고(뷰는 daum_foreign 이 채워진 행만
        # 다음 차트에 넣는다) 다음 실행까지 화면에서 빠진다.
        #
        # 며칠치를 받으면 늦게 올라온 날도 그다음 실행이 저절로 메운다. 이미
        # 있는 날은 같은 값으로 덮으므로 해가 없고, 호출 수는 그대로 한 번이다.
        per_page = 60 if mode == 'all' else LAST_MODE_DAYS

        url = f'https://finance.daum.net/api/investor/days?symbolCode={symbol}&perPage={per_page}&page=1'

        try:
            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code != 200:
                self.log.debug(f'API 호출 실패: {response.status_code}')
                return None

            result = response.json()

            if result.get('code') == 200 and result.get('data'):
                return result['data']

            return None

        except Exception as e:
            self.log.debug(f'API 호출 실패: {str(e)}')
            return None

    def save_to_db(self, stock, data_list):
        """다음 칸만 채운다. 행이 없으면 건너뛴다.

        키움 칸(individual·foreign·institution·domestic_foreign)은 null 을
        허용하지 않는다. 그래서 행을 새로 만들려면 0 을 넣어야 하는데, 그 0 은
        '자료 없음' 이 아니라 숫자 0 으로 읽힌다 — 키움 차트에 그대로 찍히고
        진짜 0 과 구분되지 않는다.

        키움은 같은 날 15:40 에, 다음은 19:40 에 돌므로 행은 이미 있다. 없다면
        키움 쪽이 실패한 날이고, 그 구멍을 가짜 0 으로 덮을 일이 아니다.
        키움이 메워진 뒤 다음 실행이 채운다 (last 모드가 며칠치를 받으므로).
        """
        updated_count = 0
        skipped_dates = []

        for item in data_list:
            try:
                date_str = item.get('date', '')[:10]
                date = datetime.strptime(date_str, '%Y-%m-%d').date()

                foreign = item.get('foreignStraightPurchaseVolume', 0) or 0
                institution = item.get('institutionStraightPurchaseVolume', 0) or 0

                updated = InvestorTrend.objects.filter(stock=stock, date=date).update(
                    daum_foreign=foreign,
                    daum_institution=institution,
                )
                if updated:
                    updated_count += 1
                else:
                    skipped_dates.append(date_str)

            except Exception as e:
                self.log.debug(f'저장 실패 ({item.get("date")}): {str(e)}')

        if skipped_dates:
            self.log.warning(
                f'{stock.name}({stock.code}) 키움 행이 없어 건너뜀: '
                f'{", ".join(skipped_dates)}'
            )

        return updated_count

    def print_data(self, data_list):
        """데이터 출력"""
        self.log.info('')
        self.log.info(f'{"날짜":<12} {"외국인순매수":>12} {"기관순매수":>12}')
        self.log.info('-' * 40)

        for item in data_list:
            date = item.get('date', '')[:10]
            foreign = item.get('foreignStraightPurchaseVolume', 0)
            institution = item.get('institutionStraightPurchaseVolume', 0)

            foreign_str = f'{foreign:>+,}'
            institution_str = f'{institution:>+,}'

            self.log.info(f'{date:<12} {foreign_str:>12} {institution_str:>12}')

        self.log.info('')
