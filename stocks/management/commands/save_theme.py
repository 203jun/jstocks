import requests
import json
from datetime import datetime, timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand
from stocks.utils import get_valid_token
from stocks.models import DailyChart, Theme
from stocks.logger import StockLogger


class Command(BaseCommand):
    help = '''
    테마 그룹 데이터 조회 및 저장 (테마그룹별요청 - ka90001)

    ※ 중요: 이 명령어를 실행하기 전에 반드시 DailyChart 데이터가 먼저 저장되어 있어야 합니다.

    동작 방식:
    1. DailyChart 테이블에서 실제 거래일을 가져옵니다 (주말/공휴일 제외)
       - 어떤 종목의 데이터든 상관없이 날짜만 중복 제거하여 사용
    2. 해당 거래일 기준으로 테마 데이터를 조회합니다
    3. 조회된 데이터에 거래일(dt)을 매핑하여 저장합니다

    실행 순서:
    1. python manage.py save_daily_chart --code [아무종목] --mode all  (먼저 실행 필수!)
       예: python manage.py save_daily_chart --code 005930 --mode all
    2. python manage.py save_theme --mode all  (이 명령어)
    '''

    def add_arguments(self, parser):
        parser.add_argument(
            '--mode',
            type=str,
            choices=['all', 'day'],
            required=True,
            help='조회 모드: all(10일 데이터), day(1일 데이터)'
        )
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        # 로거 초기화
        self.log = StockLogger(self.stdout, self.style, options, 'save_theme')

        # 1. 토큰 가져오기
        token = get_valid_token()

        if not token:
            self.log.error('토큰이 없습니다. python manage.py get_token을 먼저 실행하세요.')
            return

        # 2. DailyChart 데이터 존재 여부 확인 (필수 전제조건)
        daily_chart_count = DailyChart.objects.count()
        if daily_chart_count == 0:
            self.log.error('DailyChart 테이블이 비어있습니다!')
            self.log.debug('테마 데이터는 거래소 기준 거래일이 필요합니다.')
            self.log.debug('다음 단계를 먼저 실행하세요:')
            self.log.debug('  1. python manage.py save_daily_chart --code [아무종목] --mode all')
            return

        self.log.debug(f'DailyChart 데이터 확인 완료 ({daily_chart_count:,}개 레코드)')

        # 3. 파라미터 설정
        mode = options['mode']

        self.log.info(f'모드: {mode}')
        self.log.separator()

        # 4. 모드에 따라 처리
        try:
            if mode == 'day':
                self.fetch_day_data(token)
            elif mode == 'all':
                self.fetch_ten_days_data(token)
        except Exception as e:
            self.log.error(f'처리 중 예외 발생: {str(e)}')
            import traceback
            self.log.debug(traceback.format_exc())

    def get_recent_trading_dates(self, count=10):
        """거래소 기준 최근 거래일 목록 가져오기"""
        try:
            recent_dates = (
                DailyChart.objects
                .values_list('date', flat=True)
                .order_by('-date')
                .distinct()[:count]
            )

            dates_list = list(recent_dates)

            if len(dates_list) < count:
                self.log.warning(
                    f'DailyChart에 {len(dates_list)}개 거래일만 있습니다. '
                    f'{count}개 요청했지만 가능한 만큼만 조회합니다.'
                )

            return dates_list

        except Exception as e:
            self.log.error(f'거래일 조회 실패: {str(e)}')
            return []

    def fetch_day_data(self, token):
        """1일 데이터 조회"""
        self.log.header('1일 테마 데이터 조회')

        # 1. 거래소 기준 최근 거래일 1개 가져오기
        recent_dates = self.get_recent_trading_dates(count=1)

        if not recent_dates:
            self.log.error('거래일을 가져올 수 없습니다.')
            return

        target_date = recent_dates[0]
        self.log.debug(f'조회 대상 날짜: {target_date} (거래소 기준 최근 거래일)')

        # 2. API 파라미터 설정
        params = {
            'qry_tp': '0',
            'stk_cd': '',
            'date_tp': '1',
            'thema_nm': '',
            'flu_pl_amt_tp': '1',
            'stex_tp': '1',
        }

        # 3. API 호출
        response_data = self.call_api(token, params)

        if not response_data:
            self.log.error('API 응답 데이터가 없습니다.')
            return

        # 4. 응답 데이터 파싱
        data_key = self.find_data_key(response_data)

        if not data_key or not response_data[data_key]:
            self.log.warning('조회된 테마 데이터가 없습니다.')
            return

        data_list = response_data[data_key]

        # 5. 각 데이터에 날짜 정보 추가
        for item in data_list:
            item['dt'] = target_date.strftime('%Y%m%d')

        self.log.debug(f'조회 날짜: {target_date} (거래소 기준)')
        self.log.debug(f'조회된 테마 개수: {len(data_list)}개')

        # 6. DB에 저장
        self.save_to_db(data_list)

    def fetch_ten_days_data(self, token):
        """10일 데이터 조회"""
        self.log.header('10일 테마 데이터 조회')

        # 1. 거래소 기준 최근 거래일 10개 가져오기
        recent_dates = self.get_recent_trading_dates(count=10)

        if not recent_dates:
            self.log.error('거래일을 가져올 수 없습니다.')
            return

        if len(recent_dates) < 10:
            self.log.warning(
                f'{len(recent_dates)}개 거래일만 조회 가능합니다. '
                f'더 많은 데이터를 원하면 DailyChart 데이터를 먼저 충분히 저장하세요.'
            )

        all_data = []
        success_count = 0
        fail_count = 0

        # 2. 최근 거래일 각각에 대해 API 호출
        for idx, target_date in enumerate(recent_dates, start=1):
            self.log.debug(f'[{idx}/{len(recent_dates)}] {target_date} 데이터 조회 중...')

            # API 파라미터 설정
            params = {
                'qry_tp': '0',
                'stk_cd': '',
                'date_tp': str(idx),
                'thema_nm': '',
                'flu_pl_amt_tp': '1',
                'stex_tp': '1',
            }

            # API 호출
            response_data = self.call_api(token, params)

            if not response_data:
                self.log.debug(f'  → API 호출 실패')
                fail_count += 1
                continue

            # 응답 데이터 파싱
            data_key = self.find_data_key(response_data)

            if not data_key or not response_data[data_key]:
                self.log.debug(f'  → 데이터 없음')
                fail_count += 1
                continue

            data_list = response_data[data_key]

            # 각 데이터에 날짜 정보 추가
            for item in data_list:
                item['dt'] = target_date.strftime('%Y%m%d')

            all_data.extend(data_list)
            success_count += 1
            self.log.debug(f'  → {len(data_list)}개 테마 수집 성공')

        # 3. 결과 요약 출력
        self.log.debug(f'수집 완료: 성공 {success_count}일 / 실패 {fail_count}일')
        self.log.debug(f'총 {len(all_data)}개 테마 데이터 수집')

        # 4. DB에 저장
        if all_data:
            self.save_to_db(all_data)
        else:
            self.log.warning('저장할 데이터가 없습니다.')

    def find_data_key(self, response_data):
        """응답에서 데이터 배열 키 찾기"""
        for key in ['thema_grp', 'data', 'result', 'output']:
            if key in response_data and isinstance(response_data[key], list):
                return key
        return None

    def parse_number(self, value):
        """API 응답 숫자 파싱"""
        if not value:
            return 0
        try:
            cleaned = str(value).strip().replace(',', '')
            return int(cleaned)
        except (ValueError, TypeError):
            return 0

    def parse_decimal(self, value):
        """API 응답 소수점 파싱"""
        if not value:
            return Decimal('0.00')
        try:
            cleaned = str(value).strip().replace(',', '').replace('+', '').replace('-', '')
            if not cleaned:
                return Decimal('0.00')
            return Decimal(cleaned)
        except (ValueError, TypeError):
            return Decimal('0.00')

    def parse_date(self, date_str):
        """날짜 문자열을 date 객체로 변환"""
        return datetime.strptime(date_str, '%Y%m%d').date()

    def save_to_db(self, data_list):
        """수집한 테마 데이터를 DB에 저장"""
        self.log.header('DB 저장 시작')

        created_count = 0
        updated_count = 0
        error_count = 0

        for item in data_list:
            try:
                date = self.parse_date(item['dt'])

                theme, created = Theme.objects.update_or_create(
                    code=item.get('thema_grp_cd'),
                    date=date,
                    defaults={
                        'name': item.get('thema_nm', ''),
                        'stock_count': self.parse_number(item.get('stk_num')),
                        'rising_stock_count': self.parse_number(item.get('rising_stk_num')),
                        'falling_stock_count': self.parse_number(item.get('fall_stk_num')),
                        'fluctuation_rate': self.parse_decimal(item.get('flu_rt')),
                        'period_profit_rate': self.parse_decimal(item.get('dt_prft_rt')),
                    }
                )

                if created:
                    created_count += 1
                else:
                    updated_count += 1

            except Exception as e:
                error_count += 1
                self.log.error(
                    f'저장 실패 ({item.get("thema_grp_cd")} - {item.get("dt")}): {str(e)}'
                )

        # 결과 출력
        result_msg = f'저장 완료! 신규: {created_count}개, 업데이트: {updated_count}개'
        if error_count > 0:
            result_msg += f', 오류: {error_count}개'
        self.log.info(result_msg, success=True)

    def call_api(self, token, data, cont_yn='N', next_key=''):
        """테마그룹별요청 API 호출"""
        host = 'https://api.kiwoom.com'
        endpoint = '/api/dostk/thme'
        url = host + endpoint

        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'authorization': f'Bearer {token}',
            'cont-yn': cont_yn,
            'next-key': next_key,
            'api-id': 'ka90001',
        }

        try:
            response = requests.post(url, headers=headers, json=data)

            if response.status_code != 200:
                self.log.error(f'API 호출 실패: {response.status_code}')
                self.log.debug(f'응답: {response.text}')
                return None

            response_data = response.json()

            response_data['_headers'] = {
                key: response.headers.get(key)
                for key in ['next-key', 'cont-yn', 'api-id']
            }

            return response_data

        except Exception as e:
            self.log.error(f'API 호출 실패: {str(e)}')
            return None
