import requests
import json
from django.core.management.base import BaseCommand
from stocks.utils import get_valid_token
from stocks.logger import StockLogger


class Command(BaseCommand):
    help = 'API 테스트 - 종목별투자자기관별요청'

    def add_arguments(self, parser):
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        # 로거 초기화
        self.log = StockLogger(self.stdout, self.style, options, 'test_api')

        # 1. 토큰 가져오기
        token = get_valid_token()

        if not token:
            self.log.error('토큰이 없습니다. python manage.py get_token을 먼저 실행하세요.')
            return

        # 2. API 호출
        self.test_stock_investor(token)

    def test_stock_investor(self, token):
        """종목별투자자기관별요청 API 테스트"""
        # 1. 요청할 API URL
        host = 'https://api.kiwoom.com'  # 실전투자
        # host = 'https://mockapi.kiwoom.com'  # 모의투자
        endpoint = '/api/dostk/stkinfo'
        url = host + endpoint

        # 2. header 데이터
        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'authorization': f'Bearer {token}',
            'cont-yn': 'N',
            'next-key': '',
            'api-id': 'ka10059',
        }

        # 3. 요청 데이터
        params = {
            'dt': '20251125',  # 일자 YYYYMMDD
            'stk_cd': '005930',  # 종목코드 거래소별 종목코드 (KRX:039490,NXT:039490_NX,SOR:039490_AL)
            'amt_qty_tp': '1',  # 금액수량구분 1:금액, 2:수량
            'trde_tp': '0',  # 매매구분 0:순매수, 1:매수, 2:매도
            'unit_tp': '1000',  # 단위구분 1000:천주, 1:단주
        }

        try:
            # 4. http POST 요청
            response = requests.post(url, headers=headers, json=params)

            # 5. 응답 출력
            self.log.debug(f'\n응답 코드: {response.status_code}')

            self.log.debug('\n헤더:')
            header_info = {
                key: response.headers.get(key)
                for key in ['next-key', 'cont-yn', 'api-id']
            }
            self.log.debug(json.dumps(header_info, indent=4, ensure_ascii=False))

            # 응답 데이터 파싱
            data = response.json()

            # 먼저 응답 구조 확인
            self.log.debug('\n\n=== 응답 구조 디버깅 ===')
            self.log.debug(f'응답의 최상위 키들: {list(data.keys())}')

            # 가능한 키들을 체크
            data_key = None
            for key in ['stk_invsr_orgn', 'invsr_stk_daly', 'stk_invsr_daly', 'data', 'result', 'output']:
                if key in data and isinstance(data[key], list):
                    data_key = key
                    self.log.debug(f'\n데이터 리스트를 찾음: {data_key}')
                    self.log.debug(f'리스트 길이: {len(data[key])}')

                    # 첫 번째 아이템 구조 확인
                    if len(data[key]) > 0:
                        first_item = data[key][0]
                        self.log.debug(f'첫 번째 아이템의 키들: {list(first_item.keys())}')
                        self.log.debug(f'첫 번째 아이템 샘플:\n{json.dumps(first_item, indent=2, ensure_ascii=False)}')
                    break

            if data_key:
                # 날짜 필터링 (20251127만)
                # 가능한 날짜 필드명들을 체크
                filtered = []
                for item in data[data_key]:
                    # dt, date, dt_tm 등 가능한 날짜 필드 체크
                    date_value = item.get('dt') or item.get('date') or item.get('dt_tm')
                    if date_value and '20251127' in str(date_value):
                        filtered.append(item)

                self.log.debug(f'\n\n=== 필터링 결과 (날짜=20251127) ===')
                self.log.debug(f'필터링된 항목 수: {len(filtered)}')
                if filtered:
                    self.log.debug(json.dumps(filtered, indent=4, ensure_ascii=False))
                else:
                    self.log.warning('20251127 날짜의 데이터가 없습니다.')
                    self.log.debug('\n\n전체 응답 데이터:')
                    self.log.debug(json.dumps(data[data_key][:3], indent=4, ensure_ascii=False))  # 처음 3개만
            else:
                self.log.debug('\n응답 데이터 (전체):')
                self.log.debug(json.dumps(data, indent=4, ensure_ascii=False))

            self.log.info('API 테스트 완료', success=True)

        except Exception as e:
            self.log.error(f'API 호출 실패: {str(e)}')
