# -*- coding: utf-8 -*-
import time

import requests
from django.core.management.base import BaseCommand, CommandError

from stocks.logger import StockLogger
from stocks.models import InfoETF


class FetchFailed(Exception):
    """못 받았다. '받을 것이 없다' 와 다른 일이다."""


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

    # 예전에는 finance.naver.com/item/main.naver 화면을 CSS 셀렉터로 긁었다.
    # 네이버가 그 화면을 Next.js 앱으로 다시 만들면서 예전 구조가 통째로
    # 사라졌다. 주소는 그대로 200 을 주고 셀렉터만 안 맞아서, 값이 넉 달
    # 가까이 멈춘 채 '성공' 으로 끝나고 있었다 — 대시보드가 차트보다 최대
    # 163% 높은 값을 보여주고 있었다.
    #
    # 지금은 모바일 화면이 쓰는 JSON 을 쓴다. 필드가 없으면 예외가 나므로
    # 같은 식으로 조용히 멈추지 않는다.
    BASIC_API = 'https://m.stock.naver.com/api/stock/{code}/basic'
    ETF_API = 'https://m.stock.naver.com/api/stock/{code}/etfAnalysis'

    HEADERS = {
        'User-Agent': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                       'AppleWebKit/537.36'),
        'Referer': 'https://m.stock.naver.com/',
        'Accept': 'application/json',
    }

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
            result = self.fetch_and_save(etf)
        except FetchFailed as e:
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
                result = self.fetch_and_save(etf)
            except FetchFailed as e:
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

    def fetch_and_save(self, etf):
        basic = self.fetch(self.BASIC_API, etf.code)
        detail = self.fetch(self.ETF_API, etf.code)

        changes = []
        update_fields = ['updated_at']

        def put(field, value, label):
            setattr(etf, field, value)
            update_fields.append(field)
            changes.append(label)

        # ── 현재가 · 등락률 ──
        # 이 둘은 없으면 실패로 본다. 화면이 보여주는 값이라 옛날 값이 남으면
        # 사람이 틀린 숫자를 보고 판단한다. 비어 있는 편이 낫다.
        price = self.to_int(basic, 'closePrice')
        put('current_price', price, f'현재가={price:,}')

        rate = self.to_float(basic, 'fluctuationsRatio')
        # 칼럼이 담을 수 있는 값인지 본다. DecimalField 한계를 넘긴 값은 저장은
        # 되지만 읽을 때 decimal.InvalidOperation 이 나서 그 종목 페이지가
        # 통째로 500 이 된다. (종목 쪽에서 실제로 겪었다 — save_stock_info 참고)
        if abs(rate) >= 10000:
            self.log.error(f'{etf.code} 등락률이 칼럼 범위를 벗어나 버림: {rate}')
        else:
            put('change_rate', rate, f'등락률={rate:+.2f}%')

        # ── 아래는 없어도 넘어간다 ──
        # ETF 마다 안 주는 항목이 있다. 하나 없다고 현재가까지 버릴 일은 아니다.
        nav = detail.get('nav')
        if nav is not None:
            put('nav', round(float(nav)), f'NAV={round(float(nav)):,}')

        # marketValueRaw 는 원 단위 정수 문자열로 온다. 칼럼은 억원이다.
        # 예전에는 "21조 6,016억" 문자열을 정규식으로 뜯어 억 단위로 맞췄다.
        raw = detail.get('marketValueRaw')
        if raw:
            cap = int(raw) // 100_000_000
            put('market_cap', cap, f'시총={cap:,}억')

        fee = detail.get('totalFee')
        if fee is not None:
            put('management_fee', fee, f'보수={fee}%')

        holdings = self.parse_holdings(detail)
        if holdings:
            put('holdings', holdings, f'구성종목={len(holdings)}개')

        etf.save(update_fields=update_fields)
        return ', '.join(changes) if changes else '변경없음'

    def fetch(self, url_template, code):
        url = url_template.format(code=code)
        try:
            r = requests.get(url, headers=self.HEADERS, timeout=10)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            raise FetchFailed(f'{url.rsplit("/", 1)[-1]} 조회 실패: {e}') from e
        if not isinstance(data, dict):
            raise FetchFailed(f'{url.rsplit("/", 1)[-1]} 응답 모양이 다르다: {str(data)[:120]}')
        return data

    def parse_holdings(self, detail):
        """구성종목 상위 10개.

        예전 HTML 에서는 이름과 비중만 긁었다. API 는 종목코드도 준다 —
        화면의 보유 종목과 이어 볼 수 있다. 기존 {name, ratio} 는 화면이
        그대로 쓰고 있으므로 모양을 바꾸지 않고 code 만 더한다.
        """
        rows = detail.get('etfTop10MajorConstituentAssets') or []
        out = []
        for row in rows:
            name = row.get('itemName')
            weight = row.get('etfWeight')
            if not name or weight is None:
                continue
            # etfWeight 는 '34.43%' 꼴의 문자열로 온다. 화면이 그대로
            # 찍으므로 손대지 않고 넘긴다 — 예전 HTML 에서 긁던 모양과 같다.
            out.append({
                'name': name,
                'ratio': str(weight),
                'code': row.get('itemCode') or '',
            })
        return out[:10]

    def to_int(self, data, key):
        """'83,115' -> 83115. 없거나 숫자가 아니면 실패로 올린다."""
        value = data.get(key)
        if value in (None, '', '-'):
            raise FetchFailed(f'{key} 가 비어 있다 (응답 모양이 바뀌었을 수 있다)')
        try:
            return int(str(value).replace(',', '').replace('+', '').strip())
        except ValueError as e:
            raise FetchFailed(f'{key} 를 숫자로 읽지 못했다: {value!r}') from e

    def to_float(self, data, key):
        value = data.get(key)
        if value in (None, '', '-'):
            raise FetchFailed(f'{key} 가 비어 있다 (응답 모양이 바뀌었을 수 있다)')
        try:
            return float(str(value).replace(',', '').replace('+', '').strip())
        except ValueError as e:
            raise FetchFailed(f'{key} 를 숫자로 읽지 못했다: {value!r}') from e
