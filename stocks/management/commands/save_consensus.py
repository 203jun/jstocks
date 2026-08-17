# -*- coding: utf-8 -*-
import time
from decimal import Decimal, InvalidOperation

import requests
from django.core.management.base import BaseCommand

from stocks.logger import StockLogger
from stocks.models import Consensus, Info


class Command(BaseCommand):
    help = '''
컨센서스 수집 (WiseReport)

화면에서 손으로 붙여넣던 표를 자동으로 받아온다. 탭(연간/분기)이 주소를
바꾸지 않아 크롤링이 어려워 보이지만, 실제로는 AJAX 로 데이터만 갈아끼우며
그 응답이 JSON 이라 HTML 파싱이 필요 없다.

분기 실적이라 자주 바뀌지 않는다. 주간 배치로 충분하다.

옵션:
  --code      (선택) 종목코드 / all (전체 활성) / fav (관심·대기, 기본값)
  --dry-run   (선택) 저장하지 않고 바뀔 내용만 출력
  --log-level (선택) debug / info / error (기본값: info)

예시:
  python manage.py save_consensus
  python manage.py save_consensus --code 107640
  python manage.py save_consensus --code all --dry-run
'''

    URL = 'https://comp.wisereport.co.kr/company/ajax/c1050001_data.aspx'
    USER_AGENT = (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/126.0 Safari/537.36'
    )

    # 응답 키 -> 모델 필드. 사이트 표와 저장 필드가 1:1 로 맞는다.
    FIELD_MAP = {
        'SALES': ('revenue', 'decimal'),
        'YOY': ('yoy', 'decimal'),
        'OP': ('operating_profit', 'decimal'),
        'NP': ('net_income', 'decimal'),
        'EPS': ('eps', 'int'),
        'BPS': ('bps', 'int'),
        'PER': ('per', 'decimal'),
        'PBR': ('pbr', 'decimal'),
        'ROE': ('roe', 'decimal'),
        'EV': ('ev_ebitda', 'decimal'),
    }

    MONTH_TO_QUARTER = {3: '1Q', 6: '2Q', 9: '3Q', 12: '4Q'}

    REQUEST_INTERVAL = 0.3

    def add_arguments(self, parser):
        parser.add_argument('--code', type=str, default='fav',
                            help='종목코드 / all / fav (기본값: fav)')
        parser.add_argument('--dry-run', action='store_true',
                            help='저장하지 않고 바뀔 내용만 출력')
        StockLogger.add_arguments(parser)

    # ------------------------------------------------------------------ #

    def handle(self, *args, **options):
        self.log = StockLogger(self.stdout, self.style, options, 'save_consensus')
        self.dry_run = options['dry_run']

        code = (options['code'] or 'fav').lower()
        if code == 'all':
            stocks = Info.objects.filter(is_active=True)
            target = '전체 종목'
        elif code == 'fav':
            stocks = Info.objects.filter(is_active=True, interest_level__isnull=False)
            target = '관심 종목'
        else:
            stocks = Info.objects.filter(code=options['code'])
            target = options['code']
            if not stocks.exists():
                self.log.error(f'종목 정보 없음: {options["code"]}')
                return

        stocks = list(stocks.order_by('code').values_list('code', 'name'))
        self.log.info(f'컨센서스 수집 시작 (대상: {target} {len(stocks)}개)'
                      + (' [dry-run]' if self.dry_run else ''))

        created = updated = skipped = 0
        no_data = []
        errors = []
        for idx, (stock_code, name) in enumerate(stocks, start=1):
            try:
                # 연간 표와 분기 표를 따로 받아 어느 쪽인지 함께 들고 다닌다.
                # 연간 12월 행을 분기 규칙으로 읽으면 4분기 행을 덮어써 버린다.
                rows = ([(r, True) for r in self.fetch(stock_code, frq=0)]
                        + [(r, False) for r in self.fetch(stock_code, frq=1)])
            except Exception as exc:
                self.log.error(f'[{idx}/{len(stocks)}] {stock_code} {name}: 조회 실패 - {exc}')
                errors.append((stock_code, name, str(exc)))
                continue

            if not rows:
                # 우선주처럼 컨센서스가 없는 종목은 빈 배열이 온다. 오류가 아니다.
                no_data.append(f'{stock_code} {name}')
                self.log.debug(f'[{idx}/{len(stocks)}] {stock_code} {name}: 컨센서스 없음')
                continue

            c, u, s, changes = self.save(stock_code, rows)
            created += c
            updated += u
            skipped += s
            if c or u:
                self.log.info(f'[{idx}/{len(stocks)}] {stock_code} {name}: '
                              f'신규 {c}건, 변경 {u}건, 유지 {s}건')
                for line in changes:
                    self.log.info(f'    {line}')
            else:
                self.log.debug(f'[{idx}/{len(stocks)}] {stock_code} {name}: 변경 없음 ({s}건)')

            if idx < len(stocks):
                time.sleep(self.REQUEST_INTERVAL)

        self.log.separator()
        if no_data:
            self.log.info(f'컨센서스 없음 {len(no_data)}개: {", ".join(no_data[:8])}'
                          + (' …' if len(no_data) > 8 else ''))
        if errors:
            self.log.error(f'조회 실패 {len(errors)}개')
        self.log.info(
            f'완료 | 신규 {created}건, 변경 {updated}건, 유지 {skipped}건'
            + (' [dry-run — 저장하지 않음]' if self.dry_run else ''),
            success=True,
        )

    # ------------------------------------------------------------------ #

    def fetch(self, code, frq):
        """
        frq=0 연간, frq=1 분기.

        sDT(기준일)와 finGubun 도 페이지가 함께 보내지만 서버가 무시한다.
        (여섯 가지 값으로 확인 — 생략해도 응답이 바이트 단위로 같다)
        굳는 날짜를 들고 다닐 이유가 없어 보내지 않는다.
        """
        response = requests.get(
            self.URL,
            headers={
                'User-Agent': self.USER_AGENT,
                'Referer': f'https://comp.wisereport.co.kr/company/c1050001.aspx?cmp_cd={code}&cn=',
            },
            params={'flag': '2', 'cmp_cd': code, 'frq': frq, 'chartType': 'svg'},
            timeout=15,
        )
        response.raise_for_status()
        return response.json().get('JsonData') or []

    def parse_row(self, row, annual):
        """
        한 행 -> (year, quarter, is_estimated, {필드: 값}).
        형식을 못 읽으면 None.

        YYMM 은 '2026.03(A)' 꼴이다. (A)는 확정, (E)는 추정.
        연간 표는 전부 12월이라 분기로 환산하면 안 된다(quarter=None).
        """
        period = (row.get('YYMM') or '').strip()
        if len(period) < 10 or period[4] != '.' or period[-1] != ')':
            return None
        try:
            year, month = int(period[:4]), int(period[5:7])
        except ValueError:
            return None
        mark = period[-2]
        if mark not in ('A', 'E'):
            return None

        values = {}
        for key, (field, kind) in self.FIELD_MAP.items():
            values[field] = self.to_number(row.get(key), kind)
        quarter = None if annual else self.MONTH_TO_QUARTER.get(month)
        return year, quarter, mark == 'E', values

    @staticmethod
    def to_number(raw, kind):
        """'1,215.5' -> Decimal. 빈 값은 None (아직 추정이 안 나온 항목)."""
        text = (raw or '').strip().replace(',', '')
        if not text:
            return None
        try:
            value = Decimal(text)
        except InvalidOperation:
            return None
        return int(value) if kind == 'int' else value

    def save(self, stock_code, rows):
        """
        저장. 빈 값은 기존 값을 덮어쓰지 않는다.

        분기 추정치는 매출·영업이익만 나오고 나머지가 빈 경우가 흔하다.
        그대로 덮어쓰면 지난주에 있던 EPS·ROE 가 매주 지워진다. 빈 값은
        '아직 추정이 안 나왔다'는 뜻이지 '0' 이나 '없어졌다'가 아니다.
        """
        stock = Info.objects.get(code=stock_code)
        created = updated = skipped = 0
        changes = []

        for row, annual in rows:
            parsed = self.parse_row(row, annual)
            if not parsed:
                continue
            year, quarter, is_estimated, values = parsed

            obj = Consensus.objects.filter(stock=stock, year=year, quarter=quarter).first()
            if obj is None:
                created += 1
                if not self.dry_run:
                    Consensus.objects.create(
                        stock=stock, year=year, quarter=quarter,
                        is_estimated=is_estimated, **values,
                    )
                continue

            dirty = []
            if obj.is_estimated != is_estimated:
                obj.is_estimated = is_estimated
                dirty.append('is_estimated')
            for field, value in values.items():
                if value is None:
                    continue  # 빈 값은 건드리지 않는다
                if getattr(obj, field) != value:
                    changes.append(
                        f'{year}{"/" + quarter if quarter else ""} {field}: '
                        f'{getattr(obj, field)} -> {value}'
                    )
                    setattr(obj, field, value)
                    dirty.append(field)

            if dirty:
                updated += 1
                if not self.dry_run:
                    obj.save(update_fields=dirty + ['updated_at'])
            else:
                skipped += 1

        return created, updated, skipped, changes
