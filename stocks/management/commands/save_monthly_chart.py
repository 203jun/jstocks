import requests
import json
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from stocks.utils import get_valid_token
from stocks.models import Info, MonthlyChart
from stocks.logger import StockLogger


class Command(BaseCommand):
    help = '주식 월봉 차트 조회 및 저장 (주식월봉차트조회요청 - ka10083)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--code',
            type=str,
            required=True,
            help='종목코드 (필수)'
        )
        parser.add_argument(
            '--mode',
            type=str,
            choices=['all', 'day'],
            required=True,
            help='조회 모드: all(6년 데이터), day(최근 거래월 1개월만)'
        )
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        # 로거 초기화
        self.log = StockLogger(self.stdout, self.style, options, 'save_monthly_chart')

        # 1. 토큰 가져오기
        token = get_valid_token()

        if not token:
            self.log.error('토큰이 없습니다. python manage.py get_token을 먼저 실행하세요.')
            return

        # 2. 파라미터 설정
        stock_code = options['code']
        mode = options['mode']

        self.log.info(f'종목코드: {stock_code} | 모드: {mode}')
        self.log.separator()

        # 3. 모드에 따라 처리
        if mode == 'day':
            self.fetch_latest_day(token, stock_code)
        elif mode == 'all':
            self.fetch_six_years(token, stock_code)

    def fetch_latest_day(self, token, stock_code):
        """최근 거래일 1일 데이터만 조회"""
        self.log.header('최근 거래일 데이터 조회')

        # 오늘 날짜로 API 호출
        today = datetime.now().strftime('%Y%m%d')

        params = {
            'stk_cd': stock_code,
            'base_dt': today,
            'upd_stkpc_tp': '1',  # 수정주가구분 0 or 1
        }

        response_data = self.call_api(token, params)

        if response_data:
            # 데이터 배열 찾기
            data_key = self.find_data_key(response_data)

            if data_key and response_data[data_key]:
                # 가장 최근 날짜 찾기
                all_data = response_data[data_key]
                latest_date = max(item.get('dt', '') for item in all_data if item.get('dt'))

                # 최근 날짜 데이터만 필터링
                latest_data = [
                    item for item in all_data
                    if item.get('dt') == latest_date
                ]

                self.log.debug(f'최근 거래일: {latest_date}')
                self.log.debug(f'데이터 개수: {len(latest_data)}개')

                # DB에 저장
                self.save_to_db(stock_code, latest_data)
            else:
                self.log.warning('데이터가 없습니다.')

    def fetch_six_years(self, token, stock_code):
        """6년 데이터 조회 (연속조회 포함)"""
        self.log.header('6년 데이터 조회')

        # 6년 전 날짜 계산
        six_years_ago = datetime.now() - timedelta(days=2190)  # 6년 = 2190일
        cutoff_date = six_years_ago.strftime('%Y%m%d')
        today = datetime.now().strftime('%Y%m%d')

        self.log.debug(f'조회 기간: {cutoff_date} ~ {today}')

        all_data = []
        cont_yn = 'N'
        next_key = ''

        # 연속조회로 6년치 데이터 수집
        loop_count = 0
        while True:
            loop_count += 1
            params = {
                'stk_cd': stock_code,
                'base_dt': today,
                'upd_stkpc_tp': '1',
            }

            self.log.debug(f'[루프 {loop_count}] API 호출 (cont_yn={cont_yn}, next_key={next_key[:10] if next_key else "없음"}...)')
            response_data = self.call_api(token, params, cont_yn, next_key)

            if not response_data:
                self.log.debug('응답 데이터 없음 - 중단')
                break

            # 데이터 수집
            data_key = self.find_data_key(response_data)
            if data_key:
                current_batch = response_data[data_key]
                self.log.debug(f'현재 배치 데이터 수: {len(current_batch)}개')

                if current_batch:
                    dates = [item.get('dt', '') for item in current_batch if item.get('dt')]
                    if dates:
                        oldest = min(dates)
                        newest = max(dates)
                        self.log.debug(f'날짜 범위: {oldest} ~ {newest}')

                # 6년 이내 데이터만 필터링
                filtered = [
                    item for item in current_batch
                    if item.get('dt', '') >= cutoff_date
                ]
                self.log.debug(f'필터링 후: {len(filtered)}개 추가 (cutoff: {cutoff_date})')
                all_data.extend(filtered)

                # 가장 오래된 데이터 확인
                if current_batch:
                    old_dates = [item.get('dt', '') for item in current_batch if item.get('dt')]
                    if old_dates:
                        oldest_date = min(old_dates)
                        if oldest_date < cutoff_date:
                            self.log.debug(f'6년 이전 데이터 도달 ({oldest_date}) - 중단')
                            break

            # 연속조회 확인
            header_info = response_data.get('_headers', {})
            self.log.debug(f'헤더: cont-yn={header_info.get("cont-yn")}, next-key={header_info.get("next-key")}')

            if header_info.get('cont-yn') == 'Y' and header_info.get('next-key'):
                cont_yn = 'Y'
                next_key = header_info.get('next-key')
                self.log.debug(f'연속조회 계속... (next-key: {next_key})')
            else:
                self.log.debug('연속조회 종료 - 더 이상 데이터 없음')
                break

        self.log.debug(f'총 {len(all_data)}개 데이터 수집 완료')

        # DB에 저장
        if all_data:
            self.save_to_db(stock_code, all_data)
        else:
            self.log.warning('저장할 데이터가 없습니다.')

    def find_data_key(self, response_data):
        """응답에서 데이터 배열 키 찾기"""
        # 월봉 차트 API의 가능한 응답 키들
        for key in ['stk_mth_pole_chart_qry', 'stk_month_chart', 'chart', 'data', 'result', 'output']:
            if key in response_data and isinstance(response_data[key], list):
                return key
        return None

    def parse_number(self, value):
        """
        API 응답 숫자 파싱 ("+600", "-1000" 등)
        +/- 기호 제거하고 정수로 변환
        """
        if not value:
            return 0
        # +, - 기호는 유지하되 공백 제거
        cleaned = str(value).strip().replace(',', '')
        # + 기호만 제거 (- 는 유지)
        if cleaned.startswith('+'):
            cleaned = cleaned[1:]
        try:
            return int(cleaned)
        except (ValueError, TypeError):
            return 0

    def parse_date(self, date_str):
        """날짜 문자열을 date 객체로 변환 (20250908 -> date(2025, 9, 8))"""
        return datetime.strptime(date_str, '%Y%m%d').date()

    def save_to_db(self, stock_code, data_list):
        """
        수집한 월봉 데이터를 DB에 저장

        Args:
            stock_code: 종목코드 (예: '005930')
            data_list: API 응답 데이터 리스트
        """
        self.log.header('DB 저장 시작')

        # 종목 정보 가져오기
        try:
            stock = Info.objects.get(code=stock_code)
        except Info.DoesNotExist:
            self.log.error(f'종목 정보 없음: {stock_code}')
            self.log.debug('먼저 Info 테이블에 종목 정보를 추가해주세요.')
            return

        created_count = 0
        updated_count = 0

        for item in data_list:
            try:
                # 날짜 파싱
                date = self.parse_date(item['dt'])

                # 데이터 저장 (있으면 업데이트, 없으면 생성)
                monthly_chart, created = MonthlyChart.objects.update_or_create(
                    stock=stock,
                    date=date,
                    defaults={
                        'opening_price': self.parse_number(item.get('open_pric')),
                        'high_price': self.parse_number(item.get('high_pric')),
                        'low_price': self.parse_number(item.get('low_pric')),
                        'closing_price': self.parse_number(item.get('cur_prc')),
                        'price_change': self.parse_number(item.get('pred_pre')),
                        'trading_volume': self.parse_number(item.get('trde_qty')),
                        'trading_value': self.parse_number(item.get('trde_prica')),
                    }
                )

                if created:
                    created_count += 1
                else:
                    updated_count += 1

            except Exception as e:
                self.log.error(f'저장 실패 ({item.get("dt")}): {str(e)}')

        # 결과 출력
        self.log.info(f'저장 완료! 신규: {created_count}개, 업데이트: {updated_count}개, 총합: {created_count + updated_count}개', success=True)

    def call_api(self, token, data, cont_yn='N', next_key=''):
        """주식월봉차트조회요청 API 호출"""
        # 1. 요청할 API URL
        host = 'https://api.kiwoom.com'  # 실전투자
        # host = 'https://mockapi.kiwoom.com'  # 모의투자
        endpoint = '/api/dostk/chart'
        url = host + endpoint

        # 2. header 데이터
        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'authorization': f'Bearer {token}',
            'cont-yn': cont_yn,
            'next-key': next_key,
            'api-id': 'ka10083',
        }

        try:
            # 3. http POST 요청
            response = requests.post(url, headers=headers, json=data)

            # 응답 상태 코드 확인
            if response.status_code != 200:
                self.log.error(f'API 호출 실패: {response.status_code}')
                return None

            # 응답 데이터 파싱
            response_data = response.json()

            # 헤더 정보를 응답 데이터에 포함
            response_data['_headers'] = {
                key: response.headers.get(key)
                for key in ['next-key', 'cont-yn', 'api-id']
            }

            return response_data

        except Exception as e:
            self.log.error(f'API 호출 실패: {str(e)}')
            return None
