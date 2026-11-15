# -*- coding: utf-8 -*-
import time
from decimal import Decimal, InvalidOperation

import requests
from django.core.management.base import BaseCommand, CommandError

from stocks.logger import StockLogger
from stocks.models import Financial, Info


# 결산월 -> 분기
MONTH_TO_QUARTER = {'03': '1Q', '06': '2Q', '09': '3Q', '12': '4Q'}

# 네이버 항목 이름 -> Financial 필드.
#
# 'ROE' 는 예전 화면에 'ROE(지배주주)' 로 적혀 있던 것이다. 상용에 쌓인
# 2023·2024·2025 값과 하나씩 대조해 같은 값임을 확인했다(4.15 / 9.03 / 10.85).
#
# 받아오는 항목은 이 여섯 말고도 열 가지가 더 있다 — 부채비율, 당좌비율,
# 유보율, EPS, PER, BPS, PBR, 주당배당금, 지배주주순이익, 비지배주주순이익.
# 지금 Financial 에 칸이 없어 버린다. 쓸 일이 생기면 여기에 더하면 된다.
FIELD_MAP = {
    '매출액': 'revenue',
    '영업이익': 'operating_profit',
    '당기순이익': 'net_income',
    '영업이익률': 'operating_margin',
    '순이익률': 'net_margin',
    'ROE': 'roe',
}

# 네이버는 억 단위로 준다. 칼럼은 원 단위다.
EOK = 100_000_000
MONEY_FIELDS = {'revenue', 'operating_profit', 'net_income'}


class FetchFailed(Exception):
    """못 받았다. '받을 것이 없다' 와 다른 일이다."""


class Command(BaseCommand):
    help = '''
재무제표 저장 (네이버)

연간 4기, 분기 6기를 받아 Financial 에 넣는다. 마지막 기간은 대개
컨센서스(추정치)이며 is_estimated 로 구분해 저장한다.

옵션:
  --code      (필수*) 종목코드 또는 "all" (전체 종목)
  --clear     (선택) 전체 데이터 삭제
  --log-level (선택) debug / info / warning / error (기본값: info)

  * --clear 사용 시 --code 불필요

예시:
  python manage.py save_financial_naver --code 005930
  python manage.py save_financial_naver --code all --log-level info
  python manage.py save_financial_naver --clear
'''

    # 예전에는 finance.naver.com/item/main.naver 의 재무 테이블을 CSS
    # 셀렉터로 긁었다. 네이버가 그 화면을 Next.js 앱으로 다시 만들면서
    # 구조가 통째로 사라졌다 — 주소는 200 을 주고 셀렉터만 안 맞는다.
    API = 'https://m.stock.naver.com/api/stock/{code}/finance/{period}'

    HEADERS = {
        'User-Agent': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                       'AppleWebKit/537.36'),
        'Referer': 'https://m.stock.naver.com/',
        'Accept': 'application/json',
    }

    def add_arguments(self, parser):
        parser.add_argument('--code', type=str, help='종목코드 또는 "all" (전체 종목)')
        parser.add_argument('--clear', action='store_true', help='전체 데이터 삭제')
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        if options.get('clear'):
            deleted_count, _ = Financial.objects.all().delete()
            self.stdout.write(self.style.SUCCESS(f'Financial 데이터 {deleted_count}건 삭제 완료'))
            return

        if not options.get('code'):
            self.print_help('manage.py', 'save_financial_naver')
            return

        self.log = StockLogger(self.stdout, self.style, options, 'save_financial_naver')
        stock_code = options['code']

        if stock_code.lower() == 'all':
            self.process_all_stocks()
        else:
            self.process_single_stock(stock_code)

    def process_single_stock(self, stock_code):
        try:
            info = Info.objects.get(code=stock_code)
        except Info.DoesNotExist:
            raise CommandError(f'종목코드 {stock_code}가 Info에 없습니다.')

        self.log.info(f'종목: {info.name}({stock_code})')
        self.log.separator()

        try:
            records = self.fetch_financials(stock_code)
        except FetchFailed as e:
            raise CommandError(f'{stock_code} {info.name}: {e}')

        if not records:
            self.log.warning('받을 재무 데이터가 없습니다.')
            return

        self.save_records(info, records)

    def process_all_stocks(self):
        stocks = list(Info.objects.filter(is_active=True).values_list('code', 'name'))
        total = len(stocks)

        self.log.info(f'재무제표 저장 시작 (대상: {total}개 종목)')

        success_count = 0
        no_data_list = []
        error_list = []

        for idx, (code, name) in enumerate(stocks, 1):
            try:
                records = self.fetch_financials(code)
            except FetchFailed as e:
                self.log.error(f'[{idx}/{total}] {code} {name}: {e}')
                error_list.append((code, name, str(e)))
                time.sleep(0.3)
                continue
            except Exception as e:
                self.log.error(f'[{idx}/{total}] {code} {name}: 실패 - {e}')
                error_list.append((code, name, str(e)))
                time.sleep(0.3)
                continue

            if not records:
                self.log.info(f'[{idx}/{total}] {code} {name}: 데이터 없음')
                no_data_list.append((code, name))
            else:
                info = Info.objects.get(code=code)
                saved, updated, skipped = self.save_records(info, records, silent=True)
                self.log.info(f'[{idx}/{total}] {code} {name}: '
                              f'신규 {saved}건, 업데이트 {updated}건, 스킵 {skipped}건')
                success_count += 1
            time.sleep(0.3)

        self.log.separator()
        if error_list:
            self.log.info(f'완료 | 성공: {success_count}개, 데이터없음: {len(no_data_list)}개, '
                          f'오류: {len(error_list)}개', success=True)
            self.log.info('')
            self.log.info('[오류 목록]')
            for code, name, err in error_list:
                self.log.error(f'  {code} {name}: {err}')
        elif no_data_list:
            self.log.info(f'완료 | 성공: {success_count}개, '
                          f'데이터없음: {len(no_data_list)}개', success=True)
        else:
            self.log.info(f'완료 | 성공: {success_count}개', success=True)

        # 한 종목도 못 받았으면 비정상 종료로 끝낸다. 로그만 찍고 0 으로 끝나면
        # 배치가 '완료' 를 보낸다 — ETF 쪽이 그렇게 넉 달을 멈춰 있었다.
        if error_list and success_count == 0:
            raise CommandError(
                f'재무 데이터를 한 종목도 받지 못했습니다 ({len(error_list)}개 전부). '
                '네이버가 응답 모양을 바꾼 것으로 봐야 합니다.'
            )

    # ── 받아오기 ────────────────────────────────────────────────────

    def fetch_financials(self, code):
        """연간 + 분기를 한 줄로 늘어놓는다.

        반환: [{'year','quarter','is_estimated','values':{항목:문자열}}, ...]
        """
        records = []
        for period in ('annual', 'quarter'):
            records.extend(self.fetch_period(code, period))
        return records

    def fetch_period(self, code, period):
        url = self.API.format(code=code, period=period)
        try:
            r = requests.get(url, headers=self.HEADERS, timeout=10)
            # 상장폐지·신규상장이면 404 다. 종목이 없는 것이지 고장이 아니다.
            if r.status_code == 404:
                return []
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            raise FetchFailed(f'{period} 조회 실패: {e}') from e

        data = data or {}
        if 'financeInfo' not in data:
            raise FetchFailed(
                f'{period} 응답 모양이 다르다 (financeInfo 없음): {str(data)[:120]}')

        info = data['financeInfo']
        if info is None:
            # 재무제표가 없는 종목이다 — 인프라펀드·리츠처럼 네이버가 아예 안
            # 들고 있는 것들이 있다(맥쿼리인프라, KB발해인프라, 맵스리얼티 …).
            # 응답은 멀쩡하고 '없다' 고 분명히 말하고 있으므로 고장이 아니다.
            return []

        titles = info.get('trTitleList')
        rows = info.get('rowList')
        if titles is None or rows is None:
            raise FetchFailed(
                f'{period} 응답 모양이 다르다 (trTitleList/rowList 없음): {str(data)[:120]}')

        # 항목 이름 -> {기간키: 값}
        by_name = {}
        for row in rows:
            title = row.get('title')
            if title in FIELD_MAP:
                by_name[title] = {k: (v or {}).get('value')
                                  for k, v in (row.get('columns') or {}).items()}

        out = []
        for t in titles:
            key = t.get('key')            # '202512'
            if not key or len(key) != 6:
                continue
            year, month = int(key[:4]), key[4:]
            quarter = MONTH_TO_QUARTER.get(month)
            if not quarter:
                continue
            out.append({
                'year': year,
                # 연간은 quarter=None 으로 둔다. 모델이 그렇게 구분한다.
                'quarter': None if period == 'annual' else quarter,
                # 마지막 기간은 대개 컨센서스다. 네이버가 깃발로 알려준다 —
                # 예전에는 머리글의 '(E)' 를 정규식으로 찾아냈다.
                'is_estimated': t.get('isConsensus') == 'Y',
                'values': {name: cols.get(key) for name, cols in by_name.items()},
            })
        return out

    # ── 저장 ────────────────────────────────────────────────────────

    def save_records(self, info, records, silent=False):
        saved = updated = skipped = 0
        for rec in records:
            result = self.save_one(info, rec)
            if result == 'created':
                saved += 1
            elif result == 'updated':
                updated += 1
            else:
                skipped += 1

        if not silent:
            self.log.info(f'{info.name}({info.code}) 저장 완료: '
                          f'신규 {saved}건, 업데이트 {updated}건, 스킵 {skipped}건',
                          success=True)
        return saved, updated, skipped

    def save_one(self, info, rec):
        new_data = {'is_estimated': rec['is_estimated']}
        for name, field in FIELD_MAP.items():
            raw = rec['values'].get(name)
            if field in MONEY_FIELDS:
                value = self.parse_int(raw)
                new_data[field] = value * EOK if value is not None else None
            else:
                new_data[field] = self.parse_decimal(raw)

        existing = Financial.objects.filter(
            stock=info, year=rec['year'], quarter=rec['quarter']).first()

        if existing is None:
            Financial.objects.create(stock=info, year=rec['year'],
                                     quarter=rec['quarter'], **new_data)
            return 'created'

        if all(getattr(existing, f) == v for f, v in new_data.items()):
            return 'skipped'

        for field, value in new_data.items():
            setattr(existing, field, value)
        existing.save()
        return 'updated'

    def parse_int(self, value):
        """'3,336,059' -> 3336059 (억원)"""
        if value in (None, '', '-'):
            return None
        try:
            return int(str(value).replace(',', '').strip())
        except (ValueError, TypeError):
            return None

    def parse_decimal(self, value):
        """'13.07' -> Decimal('13.07')"""
        if value in (None, '', '-'):
            return None
        try:
            return Decimal(str(value).replace(',', '').strip())
        except InvalidOperation:
            return None
