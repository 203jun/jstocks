import requests
import json
from decimal import Decimal, InvalidOperation
from django.core.management.base import BaseCommand
from stocks.models import Info
from stocks.utils import get_valid_token
from stocks.logger import StockLogger


class Command(BaseCommand):
    help = '종목 기본정보 조회 및 저장 (주식기본정보요청 - ka10001)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--code',
            type=str,
            required=True,
            help='종목코드 (필수)'
        )
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        # 로거 초기화
        self.log = StockLogger(self.stdout, self.style, options, 'save_stock_info')

        # 1. 토큰 가져오기
        token = get_valid_token()

        if not token:
            self.log.error('토큰이 없습니다. python manage.py get_token을 먼저 실행하세요.')
            return

        # 2. API 호출
        stock_code = options['code']

        self.log.info(f'종목코드: {stock_code}')
        self.log.separator()

        response_data = self.call_api(token, stock_code)

        if response_data:
            self.log.debug(f'\n응답 데이터:\n{json.dumps(response_data, indent=2, ensure_ascii=False)}')
            # 3. DB 저장
            self.save_to_db(response_data)
        else:
            self.log.error('API 호출 실패')

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

    def save_to_db(self, data):
        """API 응답 데이터를 DB에 저장"""
        stock_code = data.get('stk_cd')
        stock_name = data.get('stk_nm')

        if not stock_code or not stock_name:
            self.log.error('종목코드 또는 종목명이 없습니다')
            return

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

        info.save()

        action = '생성' if created else '업데이트'
        self.log.info(f'{stock_name}({stock_code}) {action} 완료', success=True)
