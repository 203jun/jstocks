import requests
import json
import time
from datetime import datetime
from decimal import Decimal
from django.core.management.base import BaseCommand
from stocks.utils import get_valid_token
from stocks.models import DailyChart, Sector


class Command(BaseCommand):
    help = '''
    업종별 투자자 순매수 데이터 저장 (업종별투자자순매수요청 - ka10051)

    ※ 동작 방식:
    1. DailyChart에서 실제 거래일 가져오기
       - 어떤 종목의 데이터든 상관없이 날짜만 중복 제거하여 사용
       - 주말/공휴일은 자동으로 제외됨
    2. 각 거래일마다 API를 2번 호출:
       - mrkt_tp='0' → KOSPI 업종 데이터
       - mrkt_tp='1' → KOSDAQ 업종 데이터
    3. 응답에서 업종별 투자자 순매수 데이터 파싱
    4. Sector 테이블에 저장

    ※ 전제조건:
    - DailyChart 테이블에 일봉 데이터가 먼저 저장되어 있어야 함
    - 업종 데이터는 시계열 데이터로, 같은 업종이 날짜별로 여러 레코드 존재
    - KOSPI와 KOSDAQ은 별도로 저장 (market 필드로 구분)

    ※ 실행 순서:
    1. python manage.py save_daily_chart --code [아무종목] --mode all  (먼저 실행)
    2. python manage.py save_sector --mode all  (이 명령어)

    ※ 사용 예시:
    - 최근 거래일 1일만: python manage.py save_sector --mode day
    - 최근 10일 데이터: python manage.py save_sector --mode all
    '''

    def add_arguments(self, parser):
        parser.add_argument(
            '--mode',
            type=str,
            choices=['all', 'day'],
            required=True,
            help='조회 모드: all(10일 데이터), day(최근 거래일 1일만)'
        )

    def handle(self, *args, **options):
        # 1. 토큰 가져오기
        token = get_valid_token()

        if not token:
            self.stdout.write(self.style.ERROR('토큰이 없습니다. python manage.py get_token을 먼저 실행하세요.'))
            return

        # 2. DailyChart 데이터 확인
        daily_count = DailyChart.objects.count()
        if daily_count == 0:
            self.stdout.write(self.style.ERROR('\n[오류] DailyChart 테이블이 비어있습니다!'))
            self.stdout.write(self.style.WARNING('먼저 다음 명령어를 실행하세요:'))
            self.stdout.write('  python manage.py save_daily_chart --code [종목코드] --mode all\n')
            return

        self.stdout.write(self.style.SUCCESS(f'✓ DailyChart 데이터 확인 완료 ({daily_count:,}개 레코드)'))

        # 3. 거래일 가져오기
        mode = options['mode']
        trading_dates = self.get_trading_dates(mode)

        if not trading_dates:
            self.stdout.write(self.style.ERROR('\n거래일 데이터가 없습니다.'))
            return

        self.stdout.write(f'\n총 {len(trading_dates)}일 데이터 수집 예정')
        self.stdout.write(f'기간: {trading_dates[-1]} ~ {trading_dates[0]}')
        self.stdout.write('=' * 70)

        # 4. 각 거래일에 대해 KOSPI + KOSDAQ 데이터 수집
        self.process_all_dates(token, trading_dates)

    def get_trading_dates(self, mode):
        """
        DailyChart에서 실제 거래일 가져오기

        Args:
            mode: 'all' (10일) 또는 'day' (1일)

        Returns:
            list: 거래일 리스트 (최신순)
        """
        limit = 10 if mode == 'all' else 1

        # DailyChart에서 중복 제거한 날짜 가져오기 (최신순)
        trading_dates = DailyChart.objects.values_list('date', flat=True)\
            .distinct()\
            .order_by('-date')[:limit]

        return list(trading_dates)

    def process_all_dates(self, token, trading_dates):
        """
        모든 거래일에 대해 업종 데이터 수집

        각 날짜마다 KOSPI(mrkt_tp=0)와 KOSDAQ(mrkt_tp=1) 2번 호출

        Args:
            token: API 인증 토큰
            trading_dates: 거래일 리스트
        """
        total_dates = len(trading_dates)
        success_count = 0
        fail_count = 0
        total_sectors = 0

        for idx, trade_date in enumerate(trading_dates, start=1):
            self.stdout.write(f'\n[{idx}/{total_dates}] {trade_date} 데이터 수집 중...')

            # date_tp 계산 (최신일=1, 1일전=2, 2일전=3, ...)
            date_tp = str(idx)

            # KOSPI 데이터 수집
            kospi_count = self.fetch_and_save_market(
                token, date_tp, '0', 'KOSPI', trade_date
            )

            # KOSDAQ 데이터 수집
            kosdaq_count = self.fetch_and_save_market(
                token, date_tp, '1', 'KOSDAQ', trade_date
            )

            if kospi_count >= 0 or kosdaq_count >= 0:
                success_count += 1
                total_sectors += (kospi_count + kosdaq_count)
                self.stdout.write(self.style.SUCCESS(
                    f'  → KOSPI {kospi_count}개 + KOSDAQ {kosdaq_count}개 = 총 {kospi_count + kosdaq_count}개 저장'
                ))
            else:
                fail_count += 1
                self.stdout.write(self.style.WARNING(f'  → 데이터 수집 실패'))

        # 최종 결과
        self.stdout.write('\n' + '=' * 70)
        self.stdout.write(self.style.SUCCESS(f'\n✓ 처리 완료!'))
        self.stdout.write(f'  - 성공: {success_count}일')
        self.stdout.write(f'  - 실패: {fail_count}일')
        self.stdout.write(f'  - 총 업종 데이터: {total_sectors}개')

    def fetch_and_save_market(self, token, date_tp, mrkt_tp, market_name, trade_date):
        """
        특정 시장(KOSPI/KOSDAQ)의 업종 데이터 수집 및 저장

        Args:
            token: API 인증 토큰
            date_tp: 날짜 구분 (1=최신일, 2=1일전, ...)
            mrkt_tp: 시장 구분 ('0'=KOSPI, '1'=KOSDAQ)
            market_name: 시장명 ('KOSPI' 또는 'KOSDAQ')
            trade_date: 실제 거래일 (date 객체)

        Returns:
            int: 저장된 업종 수 (실패시 -1)
        """
        # API 호출
        params = {
            'date_tp': date_tp,
            'mrkt_tp': mrkt_tp,
            'amt_qty_tp': '0',  # 금액:0, 수량:1
            'stex_tp': '1',  # 1:KRX, 2:NXT, 3:통합
        }

        response_data = self.call_api(token, params)

        if not response_data:
            return -1

        # 데이터 배열 찾기
        data_key = self.find_data_key(response_data)
        if not data_key or not response_data[data_key]:
            return -1

        sector_list = response_data[data_key]

        # DB에 저장
        saved_count = self.save_to_db(sector_list, market_name, trade_date)

        # API 호출 제한 방지를 위한 대기 (0.5초)
        time.sleep(0.5)

        return saved_count

    def save_to_db(self, sector_list, market, trade_date):
        """
        업종 데이터를 DB에 저장

        Args:
            sector_list: API 응답의 업종 리스트
            market: 'KOSPI' 또는 'KOSDAQ'
            trade_date: 거래일 (date 객체)

        Returns:
            int: 저장된 업종 수
        """
        created_count = 0
        updated_count = 0

        for item in sector_list:
            try:
                # 업종 데이터 저장 (있으면 업데이트, 없으면 생성)
                sector, created = Sector.objects.update_or_create(
                    code=item.get('inds_cd'),
                    date=trade_date,
                    market=market,
                    defaults={
                        'name': item.get('inds_nm', ''),
                        'individual_net_buying': self.parse_number(item.get('ind_netprps')),
                        'foreign_net_buying': self.parse_number(item.get('frgnr_netprps')),
                        'institution_net_buying': self.parse_number(item.get('orgn_netprps')),
                        'securities_net_buying': self.parse_number(item.get('sc_netprps')),
                        'insurance_net_buying': self.parse_number(item.get('insrnc_netprps')),
                        'investment_trust_net_buying': self.parse_number(item.get('invtrt_netprps')),
                        'bank_net_buying': self.parse_number(item.get('bank_netprps')),
                        'pension_fund_net_buying': self.parse_number(item.get('jnsinkm_netprps')),
                        'endowment_net_buying': self.parse_number(item.get('endw_netprps')),
                        'other_corporation_net_buying': self.parse_number(item.get('etc_corp_netprps')),
                        'private_fund_net_buying': self.parse_number(item.get('samo_fund_netprps')),
                        'domestic_foreign_net_buying': self.parse_number(item.get('native_trmt_frgnr_netprps')),
                        'nation_net_buying': self.parse_number(item.get('natn_netprps')),
                    }
                )

                if created:
                    created_count += 1
                else:
                    updated_count += 1

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'    저장 실패 ({item.get("inds_cd")}): {str(e)}')
                )

        return created_count + updated_count

    def parse_number(self, value):
        """
        API 응답 숫자 파싱 ("+100500", "-520346" 등)
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

    def find_data_key(self, response_data):
        """응답에서 데이터 배열 키 찾기"""
        for key in ['inds_netprps', 'data', 'result', 'output']:
            if key in response_data and isinstance(response_data[key], list):
                return key
        return None

    def call_api(self, token, data):
        """업종별투자자순매수요청 API 호출"""
        # 1. 요청할 API URL
        host = 'https://api.kiwoom.com'  # 실전투자
        # host = 'https://mockapi.kiwoom.com'  # 모의투자
        endpoint = '/api/dostk/sect'
        url = host + endpoint

        # 2. header 데이터
        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'authorization': f'Bearer {token}',
            'api-id': 'ka10051',
        }

        try:
            # 3. http POST 요청
            response = requests.post(url, headers=headers, json=data)

            # 응답 상태 코드 확인
            if response.status_code != 200:
                return None

            # 응답 데이터 파싱
            response_data = response.json()

            return response_data

        except Exception:
            return None
