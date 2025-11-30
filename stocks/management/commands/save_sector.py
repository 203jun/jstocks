import requests
import json
import time
from datetime import datetime
from decimal import Decimal
from django.core.management.base import BaseCommand
from stocks.utils import get_valid_token
from stocks.models import DailyChart, Sector
from stocks.logger import StockLogger


class Command(BaseCommand):
    help = '''
    업종별 투자자 순매수 데이터 저장 (업종별투자자순매수요청 - ka10051)

    ※ 동작 방식:
    1. DailyChart에서 실제 거래일 가져오기
    2. 각 거래일마다 API를 2번 호출 (KOSPI, KOSDAQ)
    3. Sector 테이블에 저장

    ※ 실행 순서:
    1. python manage.py save_daily_chart --code [아무종목] --mode all
    2. python manage.py save_sector --mode all
    '''

    def add_arguments(self, parser):
        parser.add_argument(
            '--mode',
            type=str,
            choices=['all', 'day'],
            required=True,
            help='조회 모드: all(10일 데이터), day(최근 거래일 1일만)'
        )
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        # 로거 초기화
        self.log = StockLogger(self.stdout, self.style, options, 'save_sector')

        # 1. 토큰 가져오기
        token = get_valid_token()

        if not token:
            self.log.error('토큰이 없습니다. python manage.py get_token을 먼저 실행하세요.')
            return

        # 2. DailyChart 데이터 확인
        daily_count = DailyChart.objects.count()
        if daily_count == 0:
            self.log.error('DailyChart 테이블이 비어있습니다!')
            self.log.debug('먼저 python manage.py save_daily_chart --code [종목코드] --mode all 실행')
            return

        self.log.debug(f'DailyChart 데이터 확인 완료 ({daily_count:,}개 레코드)')

        # 3. 거래일 가져오기
        mode = options['mode']
        trading_dates = self.get_trading_dates(mode)

        if not trading_dates:
            self.log.error('거래일 데이터가 없습니다.')
            return

        self.log.info(f'총 {len(trading_dates)}일 데이터 수집 예정')
        self.log.debug(f'기간: {trading_dates[-1]} ~ {trading_dates[0]}')
        self.log.separator()

        # 4. 각 거래일에 대해 KOSPI + KOSDAQ 데이터 수집
        self.process_all_dates(token, trading_dates)

    def get_trading_dates(self, mode):
        """DailyChart에서 실제 거래일 가져오기"""
        limit = 10 if mode == 'all' else 1

        trading_dates = DailyChart.objects.values_list('date', flat=True)\
            .distinct()\
            .order_by('-date')[:limit]

        return list(trading_dates)

    def process_all_dates(self, token, trading_dates):
        """모든 거래일에 대해 업종 데이터 수집"""
        total_dates = len(trading_dates)
        success_count = 0
        fail_count = 0
        total_sectors = 0

        for idx, trade_date in enumerate(trading_dates, start=1):
            self.log.debug(f'[{idx}/{total_dates}] {trade_date} 데이터 수집 중...')

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
                self.log.debug(
                    f'  → KOSPI {kospi_count}개 + KOSDAQ {kosdaq_count}개 = 총 {kospi_count + kosdaq_count}개 저장'
                )
            else:
                fail_count += 1
                self.log.debug(f'  → 데이터 수집 실패')

        # 최종 결과
        self.log.info(f'처리 완료! 성공: {success_count}일, 실패: {fail_count}일, 총 업종 데이터: {total_sectors}개', success=True)

    def fetch_and_save_market(self, token, date_tp, mrkt_tp, market_name, trade_date):
        """특정 시장의 업종 데이터 수집 및 저장"""
        params = {
            'date_tp': date_tp,
            'mrkt_tp': mrkt_tp,
            'amt_qty_tp': '0',
            'stex_tp': '1',
        }

        response_data = self.call_api(token, params)

        if not response_data:
            return -1

        data_key = self.find_data_key(response_data)
        if not data_key or not response_data[data_key]:
            return -1

        sector_list = response_data[data_key]

        saved_count = self.save_to_db(sector_list, market_name, trade_date)

        time.sleep(0.5)

        return saved_count

    def save_to_db(self, sector_list, market, trade_date):
        """업종 데이터를 DB에 저장"""
        created_count = 0
        updated_count = 0

        for item in sector_list:
            try:
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
                self.log.error(f'저장 실패 ({item.get("inds_cd")}): {str(e)}')

        return created_count + updated_count

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

    def find_data_key(self, response_data):
        """응답에서 데이터 배열 키 찾기"""
        for key in ['inds_netprps', 'data', 'result', 'output']:
            if key in response_data and isinstance(response_data[key], list):
                return key
        return None

    def call_api(self, token, data):
        """업종별투자자순매수요청 API 호출"""
        host = 'https://api.kiwoom.com'
        endpoint = '/api/dostk/sect'
        url = host + endpoint

        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'authorization': f'Bearer {token}',
            'api-id': 'ka10051',
        }

        try:
            response = requests.post(url, headers=headers, json=data)

            if response.status_code != 200:
                return None

            response_data = response.json()

            return response_data

        except Exception:
            return None
