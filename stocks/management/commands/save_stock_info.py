import time
import requests
import json
from decimal import Decimal, InvalidOperation
from django.core.management.base import BaseCommand
from stocks.models import Info
from stocks.utils import get_valid_token
from stocks.logger import StockLogger


# 기본 최소 시가총액 (1000억)
DEFAULT_MIN_CAP = 1000


class Command(BaseCommand):
    help = f'''
종목 기본정보 조회 및 저장 (키움 API ka10001)

옵션:
  --code      (필수) 종목코드 또는 "all" (전체 종목)
  --min-cap   (선택) 최소 시가총액 (억 단위, 기본값: {DEFAULT_MIN_CAP}억) - 미만은 is_active=False
  --log-level (선택) debug / info / warning / error (기본값: info)

예시:
  python manage.py save_stock_info --code 005930
  python manage.py save_stock_info --code all --log-level info
  python manage.py save_stock_info --code all --min-cap 500
'''

    def add_arguments(self, parser):
        parser.add_argument(
            '--code',
            type=str,
            help='종목코드 또는 "all" (전체 종목)'
        )
        parser.add_argument(
            '--min-cap',
            type=int,
            default=DEFAULT_MIN_CAP,
            help=f'최소 시가총액 (억 단위, 기본값: {DEFAULT_MIN_CAP}억) - 미만은 is_active=False'
        )
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        # 필수 옵션 체크
        if not options.get('code'):
            self.print_help('manage.py', 'save_stock_info')
            return

        # 로거 초기화
        self.log = StockLogger(self.stdout, self.style, options, 'save_stock_info')

        code = options['code']
        self.min_cap = options['min_cap']  # 억 단위 (API 응답 mac도 억 단위)
        process_all = code.lower() == 'all'

        # 1. 토큰 가져오기
        token = get_valid_token()

        if not token:
            self.log.error('토큰이 없습니다. python manage.py get_token을 먼저 실행하세요.')
            return

        if process_all:
            # 전체 종목 처리
            self.process_all_stocks(token, self.min_cap)
        else:
            # 단일 종목 처리
            self.process_single_stock(token, code)

    def process_single_stock(self, token, stock_code):
        """단일 종목 처리"""
        try:
            stock = Info.objects.get(code=stock_code)
            self.log.info(f'종목: {stock.name}({stock_code})')
        except Info.DoesNotExist:
            self.log.info(f'종목: {stock_code}')

        self.log.separator()

        response_data = self.call_api(token, stock_code)

        if response_data:
            self.log.debug(f'\n응답 데이터:\n{json.dumps(response_data, indent=2, ensure_ascii=False)}')
            self.save_to_db(response_data)
        else:
            self.log.error('API 호출 실패')

    def process_all_stocks(self, token, min_cap_억):
        """전체 종목 일괄 처리"""
        stocks = Info.objects.all().values_list('code', 'name', 'market')

        total_count = stocks.count()
        self.log.info(f'종목정보 저장 시작 (대상: {total_count}개 종목, 시가총액 {min_cap_억}억 기준)')

        activated_count = 0
        deactivated_count = 0
        updated_count = 0
        error_count = 0

        for idx, (code, name, market) in enumerate(stocks, 1):
            try:
                response_data = self.call_api(token, code)

                if response_data:
                    result = self.save_to_db(response_data, silent=True)
                    # mac은 억 단위
                    cap_억 = self._parse_int(response_data.get('mac')) or 0

                    if result == 'deactivated':
                        deactivated_count += 1
                        self.log.info(f'[{idx}/{total_count}] {code} {name}: {cap_억}억 (비활성화됨)')
                    elif result == 'activated':
                        activated_count += 1
                        self.log.info(f'[{idx}/{total_count}] {code} {name}: {cap_억}억 (활성화됨)')
                    else:
                        updated_count += 1
                        self.log.info(f'[{idx}/{total_count}] {code} {name}: {cap_억}억')
                else:
                    self.log.error(f'[{idx}/{total_count}] {code} {name}: API 호출 실패')
                    error_count += 1

                # API 호출 간격 (0.1초)
                time.sleep(0.1)

            except Exception as e:
                self.log.error(f'[{idx}/{total_count}] {code} {name}: 처리 실패 - {str(e)}')
                error_count += 1

        # 최종 요약
        self.log.separator()
        self.log.info(
            f'완료 | 업데이트: {updated_count}개, 활성화: {activated_count}개, 비활성화: {deactivated_count}개, 오류: {error_count}개',
            success=True
        )

    def call_api(self, token, stock_code):
        """주식기본정보요청 API 호출"""
        host = 'https://api.kiwoom.com'
        endpoint = '/api/dostk/stkinfo'
        url = host + endpoint

        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'authorization': f'Bearer {token}',
            'cont-yn': 'N',
            'next-key': '',
            'api-id': 'ka10001',
        }

        params = {
            'stk_cd': stock_code,
        }

        try:
            response = requests.post(url, headers=headers, json=params)

            self.log.debug(f'응답 코드: {response.status_code}')

            if response.status_code != 200:
                self.log.error(f'HTTP 에러: {response.status_code}')
                self.log.debug(f'응답: {response.text}')
                return None

            response_data = response.json()

            # 헤더 정보
            header_info = {
                key: response.headers.get(key)
                for key in ['next-key', 'cont-yn', 'api-id']
            }
            self.log.debug(f'헤더: {json.dumps(header_info, ensure_ascii=False)}')

            return response_data

        except Exception as e:
            self.log.error(f'API 호출 실패: {str(e)}')
            return None

    def _parse_int(self, value, absolute=False):
        """문자열을 정수로 변환 (부호 포함)"""
        if not value:
            return None
        try:
            # +, - 부호 처리
            result = int(value.replace(',', '').replace('+', ''))
            return abs(result) if absolute else result
        except (ValueError, AttributeError):
            return None

    def _parse_decimal(self, value):
        """문자열을 Decimal로 변환 (부호 포함)"""
        if not value:
            return None
        try:
            return Decimal(value.replace(',', '').replace('+', ''))
        except (InvalidOperation, AttributeError):
            return None

    def save_to_db(self, data, silent=False):
        """API 응답 데이터를 DB에 저장

        Args:
            data: API 응답 데이터
            silent: True면 로그 출력 안함 (전체 처리 시)

        Returns:
            'deactivated': 시가총액 미달로 비활성화됨
            'updated': 정상 업데이트
            'created': 신규 생성
        """
        stock_code = data.get('stk_cd')
        stock_name = data.get('stk_nm')

        if not stock_code or not stock_name:
            if not silent:
                self.log.error('종목코드 또는 종목명이 없습니다')
            return None

        # Info 조회 또는 생성
        info, created = Info.objects.get_or_create(
            code=stock_code,
            defaults={'name': stock_name, 'market': 'KOSPI'}
        )

        # 필드 업데이트
        info.name = stock_name
        info.listed_shares = self._parse_int(data.get('flo_stk'))
        info.market_cap = self._parse_int(data.get('mac'))
        info.listed_ratio = self._parse_decimal(data.get('dstr_rt'))
        info.credit_ratio = self._parse_decimal(data.get('crd_rt'))
        info.foreign_exhaustion = self._parse_decimal(data.get('for_exh_rt'))
        info.per = self._parse_decimal(data.get('per'))
        info.eps = self._parse_int(data.get('eps'))
        info.roe = self._parse_decimal(data.get('roe'))
        info.pbr = self._parse_decimal(data.get('pbr'))
        info.ev = self._parse_decimal(data.get('ev'))
        info.bps = self._parse_int(data.get('bps'))
        info.sales = self._parse_int(data.get('sale_amt'))
        info.operating_profit = self._parse_int(data.get('bus_pro'))
        info.net_income = self._parse_int(data.get('cup_nga'))
        info.year_high = self._parse_int(data.get('oyr_hgst'), absolute=True)
        info.year_low = self._parse_int(data.get('oyr_lwst'), absolute=True)
        info.high_250 = self._parse_int(data.get('250hgst'), absolute=True)
        info.low_250 = self._parse_int(data.get('250lwst'), absolute=True)
        info.high_price = self._parse_int(data.get('high_pric'), absolute=True)
        info.open_price = self._parse_int(data.get('open_pric'), absolute=True)
        info.low_price = self._parse_int(data.get('low_pric'), absolute=True)
        info.current_price = self._parse_int(data.get('cur_prc'), absolute=True)
        info.price_change = self._parse_int(data.get('pred_pre'))
        info.change_rate = self._parse_decimal(data.get('flu_rt'))
        info.volume = self._parse_int(data.get('trde_qty'))
        info.volume_change = self._parse_decimal(data.get('trde_pre'))

        # 시가총액 체크 (활성화/비활성화 처리)
        result = 'created' if created else 'updated'
        if info.market_cap is not None:
            if info.market_cap < self.min_cap:
                # 시가총액 미달 → 비활성화 (단, 관심종목은 제외)
                if info.is_active and not info.interest_level:
                    info.is_active = False
                    result = 'deactivated'
            else:
                # 시가총액 충족 → 활성화
                if not info.is_active:
                    info.is_active = True
                    result = 'activated'

        info.save()

        if not silent:
            action = '생성' if created else '업데이트'
            self.log.info(f'{stock_name}({stock_code}) {action} 완료', success=True)

        return result
