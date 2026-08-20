import json
import requests
from datetime import datetime
from decimal import Decimal, InvalidOperation
from django.core.management.base import BaseCommand
from django.db import transaction
from stocks.models import Account, DailyAccountSnapshot, Holding, Info, InfoETF
from stocks.utils import get_valid_token, send_telegram_error
from stocks.logger import StockLogger


class Command(BaseCommand):
    help = '''
계좌 일별 자산 스냅샷 저장 (키움 API ka01690)

옵션:
  --date      (선택) 조회일자 YYYYMMDD (기본값: 오늘)
  --account   (선택) 계좌 키. 생략 시 활성 계좌 전체
  --log-level (선택) debug / info / warning / error (기본값: info)

예시:
  python manage.py save_daily_account
  python manage.py save_daily_account --date 20260603
  python manage.py save_daily_account --account sub1
'''

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            default=None,
            help='조회일자 YYYYMMDD (기본값: 오늘)',
        )
        parser.add_argument(
            '--account',
            type=str,
            default=None,
            help='계좌 키 (생략 시 활성 계좌 전체)',
        )
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        self.log = StockLogger(self.stdout, self.style, options, 'save_daily_account')

        qry_dt = options.get('date') or datetime.now().strftime('%Y%m%d')
        self.log.info(f'조회일자: {qry_dt}')

        accounts = Account.objects.filter(is_active=True)
        account_key = options.get('account')
        if account_key:
            accounts = accounts.filter(key=account_key)

        accounts = list(accounts)
        if not accounts:
            msg = f'대상 계좌 없음 (--account {account_key})' if account_key else '활성 계좌가 없습니다'
            self.log.error(msg)
            send_telegram_error('save_daily_account', msg)
            return

        for account in accounts:
            self.process_account(account, qry_dt)

    def process_account(self, account, qry_dt):
        """계좌 1개분 스냅샷 + 보유 종목 수집"""
        self.log.info(f'[{account.key}] {account.name} 수집 시작')

        token = get_valid_token(account.key)
        if not token:
            self.log.error(f'[{account.key}] 토큰이 없습니다. python manage.py get_token을 먼저 실행하세요.')
            send_telegram_error('save_daily_account', f'[{account.key}] 토큰 없음')
            return

        response_data = self.call_api(token, qry_dt)
        if not response_data:
            send_telegram_error('save_daily_account', f'[{account.key}] API 호출 실패')
            return

        if response_data.get('return_code') != 0:
            msg = response_data.get('return_msg', 'unknown')
            self.log.error(f'[{account.key}] API 에러: {msg}')
            send_telegram_error('save_daily_account', f'[{account.key}] API 에러: {msg}')
            return

        self.save_to_db(account, response_data, fallback_date=qry_dt)
        self.save_holdings(account, response_data.get('day_bal_rt') or [])

    def call_api(self, token, qry_dt):
        """ka01690 일별잔고수익률 API 호출"""
        host = 'https://api.kiwoom.com'
        endpoint = '/api/dostk/acnt'
        url = host + endpoint

        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'authorization': f'Bearer {token}',
            'cont-yn': 'N',
            'next-key': '',
            'api-id': 'ka01690',
        }
        params = {'qry_dt': qry_dt}

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

    def save_to_db(self, account, data, fallback_date):
        """응답 최상위 필드를 DailyAccountSnapshot에 저장"""
        dt_str = data.get('dt') or fallback_date
        try:
            snapshot_date = datetime.strptime(dt_str, '%Y%m%d').date()
        except ValueError:
            self.log.error(f'[{account.key}] 잘못된 일자 형식: {dt_str}')
            send_telegram_error('save_daily_account', f'[{account.key}] 잘못된 일자 형식: {dt_str}')
            return

        defaults = {
            'total_buy_amount': self._parse_int(data.get('tot_buy_amt')),
            'total_eval_amount': self._parse_int(data.get('tot_evlt_amt')),
            'total_eval_profit': self._parse_int(data.get('tot_evltv_prft')),
            'profit_rate': self._parse_decimal(data.get('tot_prft_rt')),
            'deposit_balance': self._parse_int(data.get('dbst_bal')),
            'estimated_asset': self._parse_int(data.get('day_stk_asst')),
            'cash_weight': self._parse_decimal(data.get('buy_wght')),
        }

        try:
            snapshot, created = DailyAccountSnapshot.objects.update_or_create(
                account=account,
                date=snapshot_date,
                defaults=defaults,
            )
        except Exception as e:
            self.log.error(f'[{account.key}] DB 저장 실패: {str(e)}')
            send_telegram_error('save_daily_account', f'[{account.key}] DB 저장 실패: {str(e)}')
            return

        action = '생성' if created else '갱신'
        self.log.info(
            f'[{account.key}] {action} 완료 | {snapshot_date} | '
            f'추정자산 {snapshot.estimated_asset or 0:,}원 | '
            f'평가손익 {snapshot.total_eval_profit or 0:,}원 | '
            f'수익률 {snapshot.profit_rate or 0}%',
            success=True,
        )

    def save_holdings(self, account, items):
        """day_bal_rt 리스트를 해당 계좌의 Holding으로 전체 갱신"""
        parsed = []
        for item in items:
            stk_cd = (item.get('stk_cd') or '').strip()
            if not stk_cd:
                continue
            parsed.append({
                'stk_cd': stk_cd,
                'stk_nm': (item.get('stk_nm') or '').strip(),
                'rmnd_qty': self._parse_int(item.get('rmnd_qty')),
                'buy_uv': self._parse_int(item.get('buy_uv')),
                'cur_prc': self._parse_int(item.get('cur_prc')),
                'eval_amount': self._parse_int(item.get('evlt_amt')),
                'eval_profit': self._parse_int(item.get('evltv_prft')),
                'profit_rate': self._parse_decimal(item.get('prft_rt')),
                'eval_weight': self._parse_decimal(item.get('evlt_wght')),
                'buy_weight': self._parse_decimal(item.get('buy_wght')),
            })

        # Info / InfoETF 매칭 룩업
        info_codes = set(Info.objects.values_list('code', flat=True))
        etf_codes = set(InfoETF.objects.values_list('code', flat=True))

        try:
            with transaction.atomic():
                # 다른 계좌 보유 종목이 지워지지 않도록 반드시 계좌로 좁힌다
                Holding.objects.filter(account=account).delete()
                Holding.objects.bulk_create([
                    Holding(
                        account=account,
                        info_id=h['stk_cd'] if h['stk_cd'] in info_codes else None,
                        info_etf_id=h['stk_cd'] if h['stk_cd'] in etf_codes else None,
                        **h,
                    )
                    for h in parsed
                ])
        except Exception as e:
            self.log.error(f'[{account.key}] Holding 저장 실패: {str(e)}')
            send_telegram_error('save_daily_account', f'[{account.key}] Holding 저장 실패: {str(e)}')
            return

        matched = sum(1 for h in parsed if h['stk_cd'] in info_codes or h['stk_cd'] in etf_codes)
        self.log.info(
            f'[{account.key}] 보유 종목 갱신 | 총 {len(parsed)}개 (Info/ETF 매칭 {matched}개)',
            success=True,
        )
        self.mark_holdings_as_interest([h['stk_cd'] for h in parsed])

    def mark_holdings_as_interest(self, codes):
        """
        보유 중인데 관심등급이 없으면 채운다.

        수급·공매도·공시·리포트는 daily_update.sh 가 --code fav 로 받는다.
        등급이 없으면 그 넷이 안 들어오는데, 화면은 보유를 관심보다 앞세워
        (views.level_of) 멀쩡하게 보인다. 돈이 들어가 있는 종목인데 판단
        재료만 조용히 비는 셈이라 실제로 세 종목이 그렇게 돼 있었다.

        등급을 채워도 화면 분류는 안 바뀐다 — 보유는 여전히 보유로 나온다.
        달라지는 것은 수집 대상에 들어온다는 것뿐이다.

        여기서 데이터를 긁지는 않는다. 이 명령 자체가 크론이고, 같은 크론의
        뒤쪽 단계가 fav 를 다시 훑는다. 여기서 부르면 두 번 받는다.
        """
        need = list(Info.objects.filter(code__in=codes, interest_level__isnull=True))
        if not need:
            return
        for stock in need:
            stock.interest_level = 'normal'
        Info.objects.bulk_update(need, ['interest_level'])
        self.log.info(
            '보유인데 관심등급이 없던 종목에 관심을 줬습니다 | '
            + ' · '.join(f'{s.name}({s.code})' for s in need),
            success=True,
        )

    def _parse_int(self, value):
        """문자열을 정수로 변환 (부호/콤마 처리, 빈 값은 None)"""
        if value is None or value == '':
            return None
        try:
            return int(str(value).replace(',', '').replace('+', ''))
        except (ValueError, AttributeError):
            return None

    def _parse_decimal(self, value):
        """문자열을 Decimal로 변환 (부호/콤마 처리, 빈 값은 None)"""
        if value is None or value == '':
            return None
        try:
            return Decimal(str(value).replace(',', '').replace('+', ''))
        except (InvalidOperation, AttributeError):
            return None
