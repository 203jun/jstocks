# -*- coding: utf-8 -*-
import time

from django.core.management.base import BaseCommand, CommandError

from stocks.etf_naver import EtfFetchFailed, NotAnEtf, fetch_etf
from stocks.logger import StockLogger
from stocks.models import InfoETF


class Command(BaseCommand):
    help = '''
ETF 정보 업데이트 (네이버)

현재가, 등락률, NAV, 시가총액, 총보수, 구성종목을 저장합니다.

옵션:
  --etf-code  (선택) ETF 코드 또는 "all" (기본값: all)
  --log-level (선택) debug / info / warning / error (기본값: info)

예시:
  python manage.py save_etf_info
  python manage.py save_etf_info --etf-code 305720
'''

    def add_arguments(self, parser):
        parser.add_argument('--etf-code', type=str, default='all',
                            help='ETF 코드 또는 "all" (기본값: all)')
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        self.log = StockLogger(self.stdout, self.style, options, 'save_etf_info')

        etf_code = options['etf_code']
        if etf_code.lower() == 'all':
            self.process_all_etfs()
        else:
            self.process_single_etf(etf_code)

    def process_single_etf(self, etf_code):
        try:
            etf = InfoETF.objects.get(code=etf_code)
        except InfoETF.DoesNotExist:
            raise CommandError(f'ETF 정보 없음: {etf_code}')

        self.log.info(f'ETF: {etf.name}({etf_code})')
        self.log.separator()

        try:
            result = self.save_one(etf)
        except (EtfFetchFailed, NotAnEtf) as e:
            raise CommandError(f'{etf.code} {etf.name}: {e}')

        self.log.info(f'결과: {result}', success=True)

    def process_all_etfs(self):
        etfs = InfoETF.objects.filter(is_active=True)
        total = etfs.count()

        if total == 0:
            self.log.warning('관심 ETF가 없습니다.')
            return

        self.log.info(f'ETF 정보 업데이트 시작 (대상: {total}개)')

        success_count = 0
        error_list = []

        for idx, etf in enumerate(etfs, 1):
            try:
                result = self.save_one(etf)
            except (EtfFetchFailed, NotAnEtf) as e:
                self.log.error(f'[{idx}/{total}] {etf.code} {etf.name}: {e}')
                error_list.append((etf.code, etf.name, str(e)))
            except Exception as e:
                self.log.error(f'[{idx}/{total}] {etf.code} {etf.name}: 실패 - {e}')
                error_list.append((etf.code, etf.name, str(e)))
            else:
                self.log.info(f'[{idx}/{total}] {etf.code} {etf.name}: {result}')
                success_count += 1
            time.sleep(0.3)

        self.log.separator()
        if error_list:
            self.log.info(f'완료 | 성공: {success_count}개, 오류: {len(error_list)}개',
                          success=True)
            self.log.info('')
            self.log.info('[오류 목록]')
            for code, name, err in error_list:
                self.log.error(f'  {code} {name}: {err}')
        else:
            self.log.info(f'완료 | 성공: {success_count}개', success=True)

        # 한 건도 못 받았으면 비정상 종료로 끝낸다. 로그만 찍고 0 으로 끝나면
        # 배치가 '완료' 를 보낸다 — 그래서 이번 고장을 넉 달 몰랐다.
        if error_list and success_count == 0:
            raise CommandError(
                f'ETF 정보를 한 건도 받지 못했습니다 ({len(error_list)}개 전부). '
                '네이버가 응답 모양을 바꾼 것으로 봐야 합니다.'
            )

    def save_one(self, etf):
        data = fetch_etf(etf.code)

        changes = []
        update_fields = ['updated_at']

        def put(field, value, label):
            setattr(etf, field, value)
            update_fields.append(field)
            changes.append(label)

        put('current_price', data['current_price'], f'현재가={data["current_price"]:,}')

        rate = data['change_rate']
        # 칼럼이 담을 수 있는 값인지 본다. DecimalField 한계를 넘긴 값은 저장은
        # 되지만 읽을 때 decimal.InvalidOperation 이 나서 그 종목 페이지가
        # 통째로 500 이 된다. (종목 쪽에서 실제로 겪었다 — save_stock_info 참고)
        if abs(rate) >= 10000:
            self.log.error(f'{etf.code} 등락률이 칼럼 범위를 벗어나 버림: {rate}')
        else:
            put('change_rate', rate, f'등락률={rate:+.2f}%')

        # 아래는 없어도 넘어간다. ETF 마다 안 주는 항목이 있고, 하나 없다고
        # 현재가까지 버릴 일은 아니다.
        if data['nav'] is not None:
            put('nav', data['nav'], f'NAV={data["nav"]:,}')
        if data['market_cap'] is not None:
            put('market_cap', data['market_cap'], f'시총={data["market_cap"]:,}억')
        if data['management_fee'] is not None:
            put('management_fee', data['management_fee'], f'보수={data["management_fee"]}%')
        if data['holdings']:
            put('holdings', data['holdings'], f'구성종목={len(data["holdings"])}개')

        etf.save(update_fields=update_fields)
        return ', '.join(changes) if changes else '변경없음'
