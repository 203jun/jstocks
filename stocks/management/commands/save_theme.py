import requests
import json
from datetime import datetime, timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand
from stocks.utils import get_valid_token
from stocks.models import DailyChart, Theme


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

    def handle(self, *args, **options):
        """
        메인 처리 함수

        Args:
            mode: 'day' (최근 거래일 1일) 또는 'all' (최근 거래일 10일)
        """
        # 1. 토큰 가져오기
        token = get_valid_token()

        if not token:
            self.stdout.write(self.style.ERROR('토큰이 없습니다. python manage.py get_token을 먼저 실행하세요.'))
            return

        # 2. DailyChart 데이터 존재 여부 확인 (필수 전제조건)
        daily_chart_count = DailyChart.objects.count()
        if daily_chart_count == 0:
            self.stdout.write(self.style.ERROR('\n[오류] DailyChart 테이블이 비어있습니다!'))
            self.stdout.write(self.style.ERROR('테마 데이터는 거래소 기준 거래일이 필요합니다.'))
            self.stdout.write(self.style.WARNING('\n다음 단계를 먼저 실행하세요:'))
            self.stdout.write('  1. python manage.py save_daily_chart --code [아무종목] --mode all')
            self.stdout.write('     예: python manage.py save_daily_chart --code 005930 --mode all')
            self.stdout.write('     (어떤 종목이든 상관없이 날짜만 사용합니다)')
            self.stdout.write('  2. python manage.py save_theme --mode all\n')
            return

        self.stdout.write(self.style.SUCCESS(f'✓ DailyChart 데이터 확인 완료 ({daily_chart_count:,}개 레코드)'))

        # 3. 파라미터 설정
        mode = options['mode']

        self.stdout.write(f'\n모드: {mode}')
        self.stdout.write('=' * 70)

        # 4. 모드에 따라 처리
        try:
            if mode == 'day':
                self.fetch_day_data(token)
            elif mode == 'all':
                self.fetch_ten_days_data(token)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\n[오류] 처리 중 예외 발생: {str(e)}'))
            import traceback
            self.stdout.write(traceback.format_exc())

    def get_recent_trading_dates(self, count=10):
        """
        거래소 기준 최근 거래일 목록 가져오기

        ※ 핵심 동작 원리:
        - DailyChart 테이블에서 실제 거래가 발생한 날짜만 추출
        - 주말(토/일), 공휴일은 자동으로 제외됨
        - 여러 종목이 있어도 날짜만 중복 제거하여 유일한 거래일만 반환

        ※ 왜 DailyChart를 사용하는가?
        - 실제 거래소에서 거래가 발생한 날짜만 정확히 알 수 있음
        - datetime.now()에서 단순히 1일씩 빼면 주말/공휴일 포함됨
        - 예: 2025-11-30(금) -> 2025-11-29(목) -> 2025-11-28(수) (실제 거래일만)
              단순 계산: 2025-11-30 -> 2025-11-29 -> 2025-11-28 -> 2025-11-27(토) ❌

        Args:
            count: 가져올 거래일 수 (기본값: 10)

        Returns:
            list: 최근 거래일 리스트 (최신순, date 객체)
                  예: [date(2025, 11, 29), date(2025, 11, 28), ...]

        Raises:
            이 메서드는 예외를 발생시키지 않음 (handle()에서 사전 체크)
        """
        try:
            # DailyChart에서 최근 거래일 가져오기
            # - values_list('date', flat=True): date 필드만 추출 (리스트 형태)
            # - order_by('-date'): 최신 날짜부터 정렬
            # - distinct(): 중복 날짜 제거 (여러 종목이 같은 날짜를 가질 수 있음)
            # - [:count]: 상위 N개만 가져오기
            recent_dates = (
                DailyChart.objects
                .values_list('date', flat=True)
                .order_by('-date')
                .distinct()[:count]
            )

            dates_list = list(recent_dates)

            # 데이터가 충분한지 확인
            if len(dates_list) < count:
                self.stdout.write(
                    self.style.WARNING(
                        f'경고: DailyChart에 {len(dates_list)}개 거래일만 있습니다. '
                        f'{count}개 요청했지만 가능한 만큼만 조회합니다.'
                    )
                )

            return dates_list

        except Exception as e:
            # 예외 발생 시 상세 로그 출력 후 빈 리스트 반환
            self.stdout.write(self.style.ERROR(f'[오류] 거래일 조회 실패: {str(e)}'))
            return []

    def fetch_day_data(self, token):
        """
        1일 데이터 조회 (거래소 기준 최근 거래일)

        동작 흐름:
        1. DailyChart에서 가장 최근 거래일 1개 조회
        2. 해당 날짜로 테마 API 호출 (date_tp='1')
        3. 응답 데이터에 날짜(dt) 필드 추가
        4. 데이터 출력

        Args:
            token: API 인증 토큰
        """
        self.stdout.write('\n[ 1일 테마 데이터 조회 ]')

        # 1. 거래소 기준 최근 거래일 1개 가져오기
        recent_dates = self.get_recent_trading_dates(count=1)

        if not recent_dates:
            self.stdout.write(self.style.ERROR('[오류] 거래일을 가져올 수 없습니다.'))
            return

        target_date = recent_dates[0]
        self.stdout.write(f'조회 대상 날짜: {target_date} (거래소 기준 최근 거래일)')

        # 2. API 파라미터 설정
        params = {
            'qry_tp': '0',  # 전체검색 (모든 테마 조회)
            'stk_cd': '',   # 종목코드 없음 (전체 테마 대상)
            'date_tp': '1',  # 1일전 데이터
            'thema_nm': '',  # 특정 테마명 지정 안 함
            'flu_pl_amt_tp': '1',  # 상위기간수익률 기준 정렬
            'stex_tp': '1',  # KRX (거래소 구분)
        }

        # 3. API 호출
        response_data = self.call_api(token, params)

        if not response_data:
            self.stdout.write(self.style.ERROR('[오류] API 응답 데이터가 없습니다.'))
            return

        # 4. 응답 데이터 파싱
        data_key = self.find_data_key(response_data)

        if not data_key or not response_data[data_key]:
            self.stdout.write(self.style.WARNING('조회된 테마 데이터가 없습니다.'))
            return

        data_list = response_data[data_key]

        # 5. 각 데이터에 날짜 정보 추가
        # API 응답에는 dt 필드가 없으므로, 수동으로 추가
        for item in data_list:
            item['dt'] = target_date.strftime('%Y%m%d')

        self.stdout.write(f'조회 날짜: {target_date} (거래소 기준)')
        self.stdout.write(f'조회된 테마 개수: {len(data_list)}개')

        # 6. DB에 저장
        self.save_to_db(data_list)

    def fetch_ten_days_data(self, token):
        """
        10일 데이터 조회 (거래소 기준 최근 10일 거래일)

        동작 흐름:
        1. DailyChart에서 최근 거래일 10개 조회 (주말/공휴일 제외)
        2. 각 거래일에 대해 API를 10번 반복 호출
           - 1번째 호출: date_tp='1' → 최근 거래일
           - 2번째 호출: date_tp='2' → 2번째 거래일
           - ...
           - 10번째 호출: date_tp='10' → 10번째 거래일
        3. 각 응답 데이터에 해당 거래일을 dt 필드로 추가
        4. 모든 데이터 수집 후 출력

        ※ 중요: 시계열 데이터 구조
        - 같은 테마(예: '2차전지')가 10개 날짜에 대해 각각 1개씩 = 총 10개 레코드
        - 이를 통해 테마별 시간에 따른 등락율, 기간수익률 추이 파악 가능

        Args:
            token: API 인증 토큰
        """
        self.stdout.write('\n[ 10일 테마 데이터 조회 ]')

        # 1. 거래소 기준 최근 거래일 10개 가져오기
        recent_dates = self.get_recent_trading_dates(count=10)

        if not recent_dates:
            self.stdout.write(self.style.ERROR('[오류] 거래일을 가져올 수 없습니다.'))
            return

        if len(recent_dates) < 10:
            self.stdout.write(
                self.style.WARNING(
                    f'주의: {len(recent_dates)}개 거래일만 조회 가능합니다. '
                    f'더 많은 데이터를 원하면 DailyChart 데이터를 먼저 충분히 저장하세요.'
                )
            )

        all_data = []
        success_count = 0
        fail_count = 0

        # 2. 최근 거래일 각각에 대해 API 호출
        for idx, target_date in enumerate(recent_dates, start=1):
            self.stdout.write(f'\n[{idx}/{len(recent_dates)}] {target_date} 데이터 조회 중... (거래소 기준)')

            # API 파라미터 설정
            params = {
                'qry_tp': '0',  # 전체검색
                'stk_cd': '',
                'date_tp': str(idx),  # n일전 (1, 2, 3, ..., 10)
                'thema_nm': '',
                'flu_pl_amt_tp': '1',  # 상위기간수익률
                'stex_tp': '1',  # KRX
            }

            # API 호출
            response_data = self.call_api(token, params)

            if not response_data:
                self.stdout.write(self.style.WARNING(f'  → API 호출 실패'))
                fail_count += 1
                continue

            # 응답 데이터 파싱
            data_key = self.find_data_key(response_data)

            if not data_key or not response_data[data_key]:
                self.stdout.write(self.style.WARNING(f'  → 데이터 없음'))
                fail_count += 1
                continue

            data_list = response_data[data_key]

            # 각 데이터에 날짜 정보 추가
            # ※ 중요: API 응답에는 dt가 없으므로, DailyChart에서 가져온 거래일을 매핑
            for item in data_list:
                item['dt'] = target_date.strftime('%Y%m%d')

            all_data.extend(data_list)
            success_count += 1
            self.stdout.write(f'  → {len(data_list)}개 테마 수집 성공')

        # 3. 결과 요약 출력
        self.stdout.write('\n' + '=' * 70)
        self.stdout.write(f'수집 완료: 성공 {success_count}일 / 실패 {fail_count}일')
        self.stdout.write(f'총 {len(all_data)}개 테마 데이터 수집')
        self.stdout.write('=' * 70)

        # 4. DB에 저장
        if all_data:
            self.save_to_db(all_data)
        else:
            self.stdout.write(self.style.WARNING('\n저장할 데이터가 없습니다.'))

    def find_data_key(self, response_data):
        """응답에서 데이터 배열 키 찾기"""
        # 테마 API의 가능한 응답 키들
        for key in ['thema_grp', 'data', 'result', 'output']:
            if key in response_data and isinstance(response_data[key], list):
                return key
        return None

    def parse_number(self, value):
        """
        API 응답 숫자 파싱
        종목수, 상승종목수, 하락종목수 등 정수 필드에 사용
        """
        if not value:
            return 0
        try:
            cleaned = str(value).strip().replace(',', '')
            return int(cleaned)
        except (ValueError, TypeError):
            return 0

    def parse_decimal(self, value):
        """
        API 응답 소수점 파싱
        등락율, 기간수익률 등 퍼센트 필드에 사용
        """
        if not value:
            return Decimal('0.00')
        try:
            # +/- 기호 제거
            cleaned = str(value).strip().replace(',', '').replace('+', '').replace('-', '')
            if not cleaned:
                return Decimal('0.00')
            return Decimal(cleaned)
        except (ValueError, TypeError):
            return Decimal('0.00')

    def parse_date(self, date_str):
        """날짜 문자열을 date 객체로 변환 (20251128 -> date(2025, 11, 28))"""
        return datetime.strptime(date_str, '%Y%m%d').date()

    def save_to_db(self, data_list):
        """
        수집한 테마 데이터를 DB에 저장

        Args:
            data_list: API 응답 데이터 리스트 (각 항목에 dt 필드 포함)

        동작:
            - Theme 모델에 update_or_create로 저장
            - 같은 테마코드(code) + 날짜(date) 조합이 있으면 업데이트
            - 없으면 신규 생성
        """
        self.stdout.write(f'\n\n[ DB 저장 시작 ]')

        created_count = 0
        updated_count = 0
        error_count = 0

        for item in data_list:
            try:
                # 날짜 파싱
                date = self.parse_date(item['dt'])

                # 데이터 저장 (있으면 업데이트, 없으면 생성)
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
                self.stdout.write(
                    self.style.ERROR(
                        f'저장 실패 ({item.get("thema_grp_cd")} - {item.get("dt")}): {str(e)}'
                    )
                )

        # 결과 출력
        self.stdout.write(self.style.SUCCESS(f'\n✓ 저장 완료!'))
        self.stdout.write(f'  - 신규 생성: {created_count}개')
        self.stdout.write(f'  - 업데이트: {updated_count}개')
        if error_count > 0:
            self.stdout.write(self.style.ERROR(f'  - 오류: {error_count}개'))
        self.stdout.write(f'  - 총합: {created_count + updated_count}개')

    def call_api(self, token, data, cont_yn='N', next_key=''):
        """테마그룹별요청 API 호출"""
        # 1. 요청할 API URL
        host = 'https://api.kiwoom.com'  # 실전투자
        # host = 'https://mockapi.kiwoom.com'  # 모의투자
        endpoint = '/api/dostk/thme'
        url = host + endpoint

        # 2. header 데이터
        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'authorization': f'Bearer {token}',
            'cont-yn': cont_yn,
            'next-key': next_key,
            'api-id': 'ka90001',
        }

        try:
            # 3. http POST 요청
            response = requests.post(url, headers=headers, json=data)

            # 응답 상태 코드 확인
            if response.status_code != 200:
                self.stdout.write(self.style.ERROR(f'API 호출 실패: {response.status_code}'))
                self.stdout.write(self.style.ERROR(f'응답: {response.text}'))
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
            self.stdout.write(self.style.ERROR(f'API 호출 실패: {str(e)}'))
            return None
