import time
import requests
from datetime import datetime, timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand
from stocks.utils import get_valid_token
from stocks.models import Info, ShortSelling
from stocks.logger import StockLogger


class Command(BaseCommand):
    help = '''
공매도 추이 저장 (키움 API ka10014)

옵션:
  --code      (필수*) 종목코드 또는 "all" (전체 종목)
  --mode      (필수*) all (60일) / last (최근 1일)
  --clear     (선택) 전체 데이터 삭제
  --log-level (선택) debug / info / warning / error (기본값: info)

  * --clear 사용 시 --code, --mode 불필요

예시:
  python manage.py save_short_selling --code 005930 --mode all
  python manage.py save_short_selling --code all --mode last --log-level info
  python manage.py save_short_selling --clear
'''

    def add_arguments(self, parser):
        parser.add_argument(
            '--code',
            type=str,
            help='종목코드 또는 "all" (전체 종목)'
        )
        parser.add_argument(
            '--mode',
            type=str,
            choices=['all', 'last'],
            help='조회 모드: all(60일), last(최근 1일)'
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='전체 데이터 삭제'
        )
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        # --clear 옵션 처리
        if options.get('clear'):
            deleted_count, _ = ShortSelling.objects.all().delete()
            self.stdout.write(self.style.SUCCESS(f'ShortSelling 데이터 {deleted_count}건 삭제 완료'))
            return

        # 필수 옵션 체크
        if not options.get('code') or not options.get('mode'):
            self.print_help('manage.py', 'save_short_selling')
            return

        self.log = StockLogger(self.stdout, self.style, options, 'save_short_selling')

        # 토큰 가져오기
        token = get_valid_token()
        if not token:
            self.log.error('토큰이 없습니다. python manage.py get_token을 먼저 실행하세요.')
            return

        code = options['code']
        mode = options['mode']

        # 전체 종목 처리
        if code.lower() == 'all':
            stocks = Info.objects.filter(is_active=True).order_by('code')
            total = stocks.count()

            self.log.info(f'공매도 추이 저장 시작 (모드: {mode}, 대상: {total}개 종목)')

            total_created = 0
            total_updated = 0
            error_list = []

            for idx, stock in enumerate(stocks, start=1):
                try:
                    created, updated = self.process_stock(token, stock.code, mode)
                    total_created += created
                    total_updated += updated
                    self.log.info(f'[{idx}/{total}] {stock.code} {stock.name}: 신규 {created}건, 업데이트 {updated}건')
                except Exception as e:
                    self.log.error(f'[{idx}/{total}] {stock.code} {stock.name}: 실패 - {str(e)}')
                    error_list.append((stock.code, stock.name, str(e)))

                if idx < total:
                    time.sleep(0.5)

            self.log.separator()
            if error_list:
                self.log.info(f'완료 | 신규: {total_created}개, 업데이트: {total_updated}개, 오류: {len(error_list)}개', success=True)
                self.log.info('')
                self.log.info('[오류 목록]')
                for code, name, err in error_list:
                    self.log.error(f'  {code} {name}: {err}')
            else:
                self.log.info(f'완료 | 신규: {total_created}개, 업데이트: {total_updated}개', success=True)

        # 단일 종목 처리
        else:
            try:
                stock = Info.objects.get(code=code)
                stock_name = stock.name
            except Info.DoesNotExist:
                stock_name = code

            self.log.info(f'종목: {stock_name}({code}) | 모드: {mode}')
            self.log.separator()

            created, updated = self.process_stock(token, code, mode)
            self.log.info(f'완료 | 신규: {created}개, 업데이트: {updated}개', success=True)

    def process_stock(self, token, stock_code, mode):
        """종목 데이터 처리 및 저장, (created, updated) 반환"""
        if mode == 'last':
            return self.fetch_latest_day(token, stock_code)
        elif mode == 'all':
            return self.fetch_sixty_days(token, stock_code)
        return 0, 0

    def fetch_latest_day(self, token, stock_code):
        """최근 거래일 1일 데이터만 조회"""
        today = datetime.now()
        week_ago = today - timedelta(days=7)

        params = {
            'stk_cd': stock_code,
            'tm_tp': '1',
            'strt_dt': week_ago.strftime('%Y%m%d'),
            'end_dt': today.strftime('%Y%m%d'),
        }

        response_data = self.call_api(token, params)

        if response_data:
            data_key = self.find_data_key(response_data)

            if data_key and response_data[data_key]:
                all_data = response_data[data_key]
                latest_date = max(item.get('dt', '') for item in all_data if item.get('dt'))

                latest_data = [
                    item for item in all_data
                    if item.get('dt') == latest_date
                ]

                self.log.debug(f'최근 거래일: {latest_date}, 데이터: {len(latest_data)}개')
                return self.save_to_db(stock_code, latest_data)

        return 0, 0

    def fetch_sixty_days(self, token, stock_code):
        """60일 데이터 조회"""
        sixty_days_ago = datetime.now() - timedelta(days=60)
        cutoff_date = sixty_days_ago.strftime('%Y%m%d')
        today = datetime.now().strftime('%Y%m%d')

        self.log.debug(f'조회 기간: {cutoff_date} ~ {today}')

        params = {
            'stk_cd': stock_code,
            'tm_tp': '1',
            'strt_dt': cutoff_date,
            'end_dt': today,
        }

        all_data = []
        cont_yn = 'N'
        next_key = ''

        loop_count = 0
        while True:
            loop_count += 1

            self.log.debug(f'[루프 {loop_count}] API 호출')
            response_data = self.call_api(token, params, cont_yn, next_key)

            if not response_data:
                break

            data_key = self.find_data_key(response_data)
            if data_key:
                current_batch = response_data[data_key]

                # 60일 이내 데이터만 필터링
                filtered = [
                    item for item in current_batch
                    if item.get('dt', '') >= cutoff_date
                ]
                all_data.extend(filtered)

                # 가장 오래된 데이터 확인
                if current_batch:
                    old_dates = [item.get('dt', '') for item in current_batch if item.get('dt')]
                    if old_dates:
                        oldest_date = min(old_dates)
                        if oldest_date < cutoff_date:
                            break

            # 연속조회 확인
            header_info = response_data.get('_headers', {})
            if header_info.get('cont-yn') == 'Y' and header_info.get('next-key'):
                cont_yn = 'Y'
                next_key = header_info.get('next-key')
            else:
                break

        self.log.debug(f'총 {len(all_data)}개 데이터 수집')

        if all_data:
            return self.save_to_db(stock_code, all_data)

        return 0, 0

    def find_data_key(self, response_data):
        """응답에서 데이터 배열 키 찾기"""
        for key in ['shrts_trnsn', 'data', 'result', 'output']:
            if key in response_data and isinstance(response_data[key], list):
                return key
        return None

    def parse_number(self, value):
        """API 응답 숫자 파싱"""
        if not value:
            return 0
        cleaned = str(value).strip().replace(',', '')
        if cleaned.startswith('+'):
            cleaned = cleaned[1:]
        try:
            return int(cleaned)
        except (ValueError, TypeError):
            return 0

    def parse_decimal(self, value):
        """API 응답 소수점 파싱"""
        if not value:
            return Decimal('0.00')
        try:
            cleaned = str(value).strip().replace(',', '')
            return Decimal(cleaned)
        except (ValueError, TypeError):
            return Decimal('0.00')

    def parse_date(self, date_str):
        """날짜 문자열을 date 객체로 변환"""
        return datetime.strptime(date_str, '%Y%m%d').date()

    def save_to_db(self, stock_code, data_list):
        """DB에 저장하고 (created, updated) 반환"""
        try:
            stock = Info.objects.get(code=stock_code)
        except Info.DoesNotExist:
            self.log.debug(f'종목 정보 없음: {stock_code}')
            return 0, 0

        created_count = 0
        updated_count = 0

        for item in data_list:
            try:
                date = self.parse_date(item['dt'])

                short_selling, created = ShortSelling.objects.update_or_create(
                    stock=stock,
                    date=date,
                    defaults={
                        'trading_volume': self.parse_number(item.get('trde_qty')),
                        'short_volume': self.parse_number(item.get('shrts_qty')),
                        'cumulative_short_volume': self.parse_number(item.get('ovr_shrts_qty')),
                        'trading_weight': self.parse_decimal(item.get('trde_wght')),
                        'short_trading_value': self.parse_number(item.get('shrts_trde_prica')),
                        'short_average_price': self.parse_number(item.get('shrts_avg_pric')),
                    }
                )

                if created:
                    created_count += 1
                else:
                    updated_count += 1

            except Exception as e:
                self.log.debug(f'저장 실패 ({item.get("dt")}): {str(e)}')

        return created_count, updated_count

    def call_api(self, token, data, cont_yn='N', next_key=''):
        """공매도추이요청 API 호출"""
        url = 'https://api.kiwoom.com/api/dostk/shsa'

        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'authorization': f'Bearer {token}',
            'cont-yn': cont_yn,
            'next-key': next_key,
            'api-id': 'ka10014',
        }

        try:
            response = requests.post(url, headers=headers, json=data)

            if response.status_code != 200:
                self.log.debug(f'API 호출 실패: {response.status_code}')
                return None

            response_data = response.json()
            response_data['_headers'] = {
                key: response.headers.get(key)
                for key in ['next-key', 'cont-yn', 'api-id']
            }

            return response_data

        except Exception as e:
            self.log.debug(f'API 호출 실패: {str(e)}')
            return None
