import requests
import json
from django.core.management.base import BaseCommand
from stocks.models import Info
from stocks.utils import get_valid_token
from stocks.logger import StockLogger


# 시장구분 코드
MARKET_CODES = [
    ('ETF', '8'),      # ETF 코드 수집 (KOSPI/KOSDAQ에서 제외용, DB 저장 안함)
    ('KOSPI', '0'),
    ('KOSDAQ', '10'),
]


class Command(BaseCommand):
    help = '''
상장 종목 목록 동기화 (키움 API ka10099)

- KOSPI, KOSDAQ 종목만 저장
- ETF는 별도 모델(InfoETF)에서 관리

옵션:
  --clear     (선택) Info 테이블 전체 삭제 (연결된 모든 데이터 함께 삭제됨)
  --log-level (선택) debug / info / warning / error (기본값: info)

예시:
  python manage.py save_stock_list
  python manage.py save_stock_list --log-level info
  python manage.py save_stock_list --clear
'''

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Info 테이블 전체 삭제 (연결된 모든 데이터 함께 삭제됨)'
        )
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        self.log = StockLogger(self.stdout, self.style, options, 'save_stock_list')

        # --clear: Info 테이블 전체 삭제
        if options['clear']:
            from django.db import connection
            with connection.cursor() as cursor:
                # 연결된 테이블들 먼저 삭제 (CASCADE 수동 처리)
                # info를 참조하는 모든 테이블 포함
                tables = [
                    'financial', 'daily_chart', 'weekly_chart', 'monthly_chart',
                    'investor_trend', 'short_selling', 'gongsi', 'nodaji', 'report',
                    'schedule', 'info_sectors', 'info'
                ]
                for table in tables:
                    try:
                        cursor.execute(f'DELETE FROM {table}')
                        self.stdout.write(f'  {table} 삭제 완료')
                    except Exception as e:
                        self.stdout.write(f'  {table} 스킵 ({e})')
            self.stdout.write(self.style.SUCCESS('Info 및 연결된 모든 테이블 삭제 완료'))
            return

        token = get_valid_token()
        if not token:
            self.log.error('토큰이 없습니다.')
            return

        etf_codes = set()

        self.log.info(f'종목목록 저장 시작 (대상: KOSPI, KOSDAQ)')

        for market, market_code in MARKET_CODES:
            response_data, response_headers = self.call_api(token, market_code)

            if response_data and 'list' in response_data:
                stock_list = response_data['list']

                if market == 'ETF':
                    # ETF 코드 수집 (KOSPI/KOSDAQ 응답에서 제외용, DB 저장 안함)
                    etf_codes = {item.get('code') for item in stock_list}
                    self.log.info(f'[ETF] {len(etf_codes)}개 코드 수집 (제외용)')
                    continue

                if market in ['KOSPI', 'KOSDAQ']:
                    original_count = len(stock_list)
                    # kind='A'(일반주식)만 필터링 + ETF/스팩 제외
                    stock_list = [
                        item for item in stock_list
                        if item.get('kind') == 'A'
                        and item.get('code') not in etf_codes
                        and not item.get('name', '').endswith('스팩')
                    ]
                    filtered_count = original_count - len(stock_list)
                    if filtered_count > 0:
                        self.log.info(f'ETN/ETF/스팩 등 {filtered_count}개 제외')

                    self.sync_stocks(market, stock_list)

    def sync_stocks(self, market, stock_list):
        """종목 목록 동기화 (INSERT/UPDATE/상폐 체크)"""
        # API에서 가져온 종목 코드 집합
        api_codes = {item.get('code') for item in stock_list}

        # DB에 있는 해당 시장의 활성 종목 코드 집합
        db_codes = set(Info.objects.filter(market=market, is_active=True).values_list('code', flat=True))

        # 신규 종목 (API에는 있고 해당 시장 DB에는 없음)
        new_codes = api_codes - db_codes

        # 상폐 종목 (DB에는 있고 API에는 없음)
        delisted_codes = db_codes - api_codes

        # 신규 종목 INSERT 또는 UPDATE
        inserted_count = 0
        updated_count = 0
        for item in stock_list:
            code = item.get('code')
            if code in new_codes:
                # 다른 시장에 이미 존재하는지 확인
                existing = Info.objects.filter(code=code).first()
                if existing:
                    # 기존 레코드 업데이트 (시장 변경 또는 재활성화)
                    old_market = existing.market
                    old_active = existing.is_active
                    existing.name = item.get('name', '')
                    existing.market = market
                    existing.is_active = True
                    existing.save()
                    self.log.debug(f'  [업데이트] {code} {item.get("name")} ({old_market}, active={old_active} → {market}, active=True)')
                    updated_count += 1
                else:
                    # 완전 신규 종목
                    Info.objects.create(
                        code=code,
                        name=item.get('name', ''),
                        market=market,
                        is_active=True,
                    )
                    self.log.debug(f'  [신규] {code} {item.get("name")}')
                    inserted_count += 1

        # 상폐 종목 로그 (강한 경고) - ERROR 레벨로 파일에도 기록
        if delisted_codes:
            self.log.error('!' * 70)
            self.log.error('!!! 상폐/제외 종목 발견 !!!')
            self.log.error('!' * 70)
            for code in delisted_codes:
                stock = Info.objects.get(code=code)
                self.log.error(f'  [상폐] {code} {stock.name}')
                # is_active = False 처리
                stock.is_active = False
                stock.save()
            self.log.error('!' * 70)

        # 결과 요약
        self.log.separator()
        self.log.info(f'[{market}] 완료 | API: {len(api_codes)}개, 신규: {inserted_count}개, 업데이트: {updated_count}개, 상폐: {len(delisted_codes)}개', success=True)

    def call_api(self, token, market_code, cont_yn='N', next_key=''):
        """종목 목록 API 호출 (ka10099)"""
        host = 'https://api.kiwoom.com'
        endpoint = '/api/dostk/stkinfo'
        url = host + endpoint

        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'authorization': f'Bearer {token}',
            'cont-yn': cont_yn,
            'next-key': next_key,
            'api-id': 'ka10099',
        }

        params = {
            'mrkt_tp': market_code,
        }

        try:
            response = requests.post(url, headers=headers, json=params)

            self.stdout.write(f'응답 코드: {response.status_code}')

            if response.status_code != 200:
                self.stdout.write(self.style.ERROR(f'HTTP 에러: {response.status_code}'))
                self.stdout.write(f'응답: {response.text}')
                return None, None

            response_headers = {
                'cont-yn': response.headers.get('cont-yn'),
                'next-key': response.headers.get('next-key'),
                'api-id': response.headers.get('api-id'),
            }

            return response.json(), response_headers

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'API 호출 실패: {str(e)}'))
            return None, None
