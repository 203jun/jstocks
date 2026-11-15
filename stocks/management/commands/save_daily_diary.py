import requests
from datetime import datetime
from decimal import Decimal, InvalidOperation
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from stocks.models import DailyTradeDiary, DailyTrade, Info, InfoETF
from stocks.utils import get_valid_token
from stocks.logger import StockLogger


class Command(BaseCommand):
    help = '''
매매일지 저장 (키움 API ka10170)

옵션:
  --date       (선택) 기준일자 YYYYMMDD (기본값: 오늘)
  --ottks-tp   (선택) 단주구분 1:당일매수에 대한 당일매도 / 2:당일매도 전체 (기본값: 2)
  --ch-crd-tp  (선택) 현금신용구분 0:전체 / 1:현금매매만 / 2:신용매매만 (기본값: 0)
  --log-level  (선택) debug / info / warning / error (기본값: info)

예시:
  python manage.py save_daily_diary
  python manage.py save_daily_diary --date 20260601
'''

    def add_arguments(self, parser):
        parser.add_argument('--date', type=str, default=None, help='기준일자 YYYYMMDD (기본값: 오늘)')
        parser.add_argument('--ottks-tp', type=str, default='2', help='단주구분 (기본값: 2)')
        parser.add_argument('--ch-crd-tp', type=str, default='0', help='현금신용구분 (기본값: 0)')
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        self.log = StockLogger(self.stdout, self.style, options, 'save_daily_diary')

        base_dt = options.get('date') or datetime.now().strftime('%Y%m%d')
        ottks_tp = options.get('ottks_tp')
        ch_crd_tp = options.get('ch_crd_tp')
        self.log.info(f'기준일자: {base_dt}, ottks_tp: {ottks_tp}, ch_crd_tp: {ch_crd_tp}')

        # 아래 셋은 종료코드로 끝낸다. 예전에는 텔레그램을 직접 보내고 0 으로
        # 끝나서, 배치는 같은 자리에서 ✅ 를 함께 보냈다. batch_lib.sh 가
        # 단계 이름과 원인을 실어 한 번만 보낸다.
        token = get_valid_token()
        if not token:
            raise CommandError('토큰이 없습니다. 먼저: python manage.py get_token')

        response_data = self.call_api(token, base_dt, ottks_tp, ch_crd_tp)
        if not response_data:
            raise CommandError(f'매매일지 API 호출 실패 (기준일 {base_dt})')

        if response_data.get('return_code') != 0:
            msg = response_data.get('return_msg', 'unknown')
            raise CommandError(f'매매일지 API 에러: {msg}')

        self.save_to_db(response_data, base_dt)

    def call_api(self, token, base_dt, ottks_tp, ch_crd_tp):
        """ka10170 매매일지 API 호출"""
        host = 'https://api.kiwoom.com'
        endpoint = '/api/dostk/acnt'
        url = host + endpoint

        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'authorization': f'Bearer {token}',
            'cont-yn': 'N',
            'next-key': '',
            'api-id': 'ka10170',
        }
        params = {
            'base_dt': base_dt,
            'ottks_tp': ottks_tp,
            'ch_crd_tp': ch_crd_tp,
        }

        try:
            response = requests.post(url, headers=headers, json=params)
            self.log.debug(f'응답 코드: {response.status_code}')
            if response.status_code != 200:
                self.log.error(f'HTTP 에러: {response.status_code}')
                self.log.debug(f'응답: {response.text}')
                return None
            return response.json()
        except Exception as e:
            self.log.error(f'API 호출 실패: {str(e)}')
            return None

    def save_to_db(self, data, base_dt):
        """diary + trades 저장 (해당 날짜의 trades 전체 갱신)"""
        try:
            diary_date = datetime.strptime(base_dt, '%Y%m%d').date()
        except ValueError:
            raise CommandError(f'잘못된 일자 형식: {base_dt}')

        diary_defaults = {
            'total_sell_amount': self._parse_int(data.get('tot_sell_amt')),
            'total_buy_amount': self._parse_int(data.get('tot_buy_amt')),
            'total_commission_tax': self._parse_int(data.get('tot_cmsn_tax')),
            'total_settlement_amount': self._parse_int(data.get('tot_exct_amt')),
            'total_pl_amount': self._parse_int(data.get('tot_pl_amt')),
            'profit_rate': self._parse_decimal(data.get('tot_prft_rt')),
        }

        # trades 파싱
        items = data.get('tdy_trde_diary') or []
        parsed_trades = []
        for item in items:
            stk_cd = (item.get('stk_cd') or '').strip()
            if not stk_cd:
                continue
            parsed_trades.append({
                'stk_cd': stk_cd,
                'stk_nm': (item.get('stk_nm') or '').strip(),
                'buy_avg_price': self._parse_int(item.get('buy_avg_pric')),
                'buy_qty': self._parse_int(item.get('buy_qty')),
                'buy_amount': self._parse_int(item.get('buy_amt')),
                'sell_avg_price': self._parse_int(item.get('sel_avg_pric')),
                'sell_qty': self._parse_int(item.get('sell_qty')),
                'sell_amount': self._parse_int(item.get('sell_amt')),
                'commission_tax': self._parse_int(item.get('cmsn_alm_tax')),
                'pl_amount': self._parse_int(item.get('pl_amt')),
                'profit_rate': self._parse_decimal(item.get('prft_rt')),
            })

        info_codes = set(Info.objects.values_list('code', flat=True))
        etf_codes = set(InfoETF.objects.values_list('code', flat=True))

        try:
            with transaction.atomic():
                diary, created = DailyTradeDiary.objects.update_or_create(
                    date=diary_date, defaults=diary_defaults,
                )
                # 해당 날짜의 trades 전체 갱신
                DailyTrade.objects.filter(diary=diary).delete()
                DailyTrade.objects.bulk_create([
                    DailyTrade(
                        diary=diary,
                        info_id=t['stk_cd'] if t['stk_cd'] in info_codes else None,
                        info_etf_id=t['stk_cd'] if t['stk_cd'] in etf_codes else None,
                        **t,
                    )
                    for t in parsed_trades
                ])
        except Exception as e:
            raise CommandError(f'매매일지 DB 저장 실패: {e}')

        action = '생성' if created else '갱신'
        matched = sum(1 for t in parsed_trades if t['stk_cd'] in info_codes or t['stk_cd'] in etf_codes)
        self.log.info(
            f'{action} 완료 | {diary_date} | 손익 {diary.total_pl_amount or 0:,}원 | '
            f'수익률 {diary.profit_rate or 0}% | 거래 {len(parsed_trades)}건 (매칭 {matched})',
            success=True,
        )

    def _parse_int(self, value):
        if value is None or value == '':
            return None
        try:
            return int(str(value).replace(',', '').replace('+', ''))
        except (ValueError, AttributeError):
            return None

    def _parse_decimal(self, value):
        if value is None or value == '':
            return None
        try:
            return Decimal(str(value).replace(',', '').replace('+', ''))
        except (InvalidOperation, AttributeError):
            return None
