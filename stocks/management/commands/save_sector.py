# -*- coding: utf-8 -*-
import time
import requests
from django.core.management.base import BaseCommand
from stocks.utils import get_valid_token
from stocks.models import Sector, DailyChart
from stocks.logger import StockLogger


class Command(BaseCommand):
    help = '''
    업종별 투자자 순매수 데이터 저장 (ka10051)

    사용법:
      python manage.py save_sector              # 최근 거래일 1일
      python manage.py save_sector --mode all   # 최근 60거래일
      python manage.py save_sector --clear      # 전체 삭제
    '''

    def add_arguments(self, parser):
        parser.add_argument(
            '--mode',
            choices=['last', 'all'],
            default='last',
            help='last: 최근 1일 (기본값), all: 최근 60거래일'
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='전체 데이터 삭제'
        )
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        # Clear existing data if requested
        if options.get('clear'):
            deleted_count = Sector.objects.all().delete()[0]
            self.stdout.write(self.style.WARNING(f'Deleted {deleted_count} existing records'))
            return

        self.log = StockLogger(self.stdout, self.style, options, 'save_sector')

        # Get token
        token = get_valid_token()
        if not token:
            self.log.error('No token. Run: python manage.py get_token')
            return

        # Get trading dates from DailyChart
        mode = options.get('mode', 'last')
        limit = 60 if mode == 'all' else 1

        trading_dates = list(
            DailyChart.objects.values_list('date', flat=True)
            .distinct()
            .order_by('-date')[:limit]
        )

        if not trading_dates:
            self.log.error('DailyChart 데이터가 없습니다.')
            self.log.error('먼저 실행: python manage.py save_daily_chart')
            return

        trading_dates.reverse()  # 오래된 날짜부터 처리

        self.log.info(f'수집 대상: {len(trading_dates)}일 ({trading_dates[0]} ~ {trading_dates[-1]})')
        self.log.separator()

        total_saved = 0
        for idx, trade_date in enumerate(trading_dates, start=1):
            date_str = trade_date.strftime('%Y%m%d')

            # KOSPI
            kospi_count = self.fetch_and_save_market(token, '0', 'KOSPI', trade_date, date_str)

            # KOSDAQ
            kosdaq_count = self.fetch_and_save_market(token, '1', 'KOSDAQ', trade_date, date_str)

            day_total = kospi_count + kosdaq_count
            total_saved += day_total

            if mode == 'all':
                self.log.debug(f'[{idx}/{len(trading_dates)}] {trade_date}: {day_total}개')
                time.sleep(0.3)  # API 호출 제한 방지
            else:
                self.log.info(f'{trade_date}: KOSPI {kospi_count}개, KOSDAQ {kosdaq_count}개')

        self.log.separator()
        self.log.info(f'완료! 총 {total_saved}개 저장', success=True)

    def fetch_and_save_market(self, token, mrkt_tp, market_name, trade_date, date_str):
        """Fetch and save sector data for a market"""
        params = {
            'mrkt_tp': mrkt_tp,
            'amt_qty_tp': '0',
            'base_dt': date_str,
            'stex_tp': '1',
        }

        response_data = self.call_api(token, params)

        if not response_data:
            return 0

        data_key = self.find_data_key(response_data)
        if not data_key or not response_data[data_key]:
            return 0

        sector_list = response_data[data_key]
        return self.save_to_db(sector_list, market_name, trade_date)

    def save_to_db(self, sector_list, market, trade_date):
        """Save sector data to DB"""
        saved_count = 0

        for item in sector_list:
            try:
                Sector.objects.update_or_create(
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
                saved_count += 1
            except Exception as e:
                self.log.error(f'Save failed ({item.get("inds_cd")}): {str(e)}')

        return saved_count

    def parse_number(self, value):
        """Parse number string"""
        if not value:
            return 0
        cleaned = str(value).strip().replace(',', '').replace('+', '')
        try:
            return int(cleaned)
        except (ValueError, TypeError):
            return 0

    def find_data_key(self, response_data):
        """Find data array key in response"""
        for key in ['inds_netprps', 'data', 'result', 'output']:
            if key in response_data and isinstance(response_data[key], list):
                return key
        return None

    def call_api(self, token, data):
        """Call ka10051 API"""
        url = 'https://api.kiwoom.com/api/dostk/sect'

        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'authorization': f'Bearer {token}',
            'api-id': 'ka10051',
        }

        try:
            response = requests.post(url, headers=headers, json=data)
            if response.status_code != 200:
                self.log.error(f'API error: {response.status_code}')
                return None
            return response.json()
        except Exception as e:
            self.log.error(f'API exception: {e}')
            return None
