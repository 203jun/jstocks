import time
import requests
from datetime import datetime
from django.core.management.base import BaseCommand
from stocks.models import Info, InvestorTrend
from stocks.logger import StockLogger


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
                stocks = stocks.filter(interest_level__isnull=False)
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

        per_page = 60 if mode == 'all' else 1

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
        """DB에 저장하고 업데이트 건수 반환"""
        updated_count = 0

        for item in data_list:
            try:
                date_str = item.get('date', '')[:10]
                date = datetime.strptime(date_str, '%Y-%m-%d').date()

                foreign = item.get('foreignStraightPurchaseVolume', 0) or 0
                institution = item.get('institutionStraightPurchaseVolume', 0) or 0

                # 기존 레코드 확인
                existing = InvestorTrend.objects.filter(stock=stock, date=date).first()

                if existing:
                    # 기존 레코드가 있으면 daum 필드만 업데이트
                    existing.daum_foreign = foreign
                    existing.daum_institution = institution
                    existing.save(update_fields=['daum_foreign', 'daum_institution'])
                else:
                    # 새로 생성 시 필수 필드 포함
                    InvestorTrend.objects.create(
                        stock=stock,
                        date=date,
                        individual=0,
                        foreign=0,
                        institution=0,
                        domestic_foreign=0,
                        daum_foreign=foreign,
                        daum_institution=institution,
                    )

                updated_count += 1

            except Exception as e:
                self.log.debug(f'저장 실패 ({item.get("date")}): {str(e)}')

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
