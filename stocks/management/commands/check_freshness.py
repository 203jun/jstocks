# -*- coding: utf-8 -*-
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from stocks.freshness import MAX_LAG_BUSINESS_DAYS, run
from stocks.logger import StockLogger


class Command(BaseCommand):
    help = '''
데이터가 늘어야 할 때 늘었는지 점검

명령이 실패하면 종료코드로 알린다. 그런데 그것으로 못 잡는 고장이 있다 —
명령은 성공했는데 입력이 썩은 경우다. 시장 수급이 석 달 끊긴 동안
save_market_indicator 는 엉터리 값을 계산하면서 날마다 '완료' 를 찍었다.

거래일마다 늘어야 하는 데이터만 본다. 무엇을 보는지는 stocks/freshness.py
의 CHECKS 에 적혀 있다.

옵션:
  --date      (선택) 오늘 대신 이 날짜 기준 (YYYY-MM-DD). 시험용
  --quiet     (선택) 문제가 있을 때만 출력. 배치에서 쓴다
  --log-level (선택) debug / info / warning / error (기본값: info)

예시:
  python manage.py check_freshness
  python manage.py check_freshness --quiet
  python manage.py check_freshness --date 2026-11-16
'''

    def add_arguments(self, parser):
        parser.add_argument('--date', type=str, default=None,
                            help='오늘 대신 이 날짜 기준 (YYYY-MM-DD)')
        parser.add_argument('--quiet', action='store_true',
                            help='문제가 있을 때만 출력')
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        self.log = StockLogger(self.stdout, self.style, options, 'check_freshness')

        today = None
        if options['date']:
            try:
                today = datetime.strptime(options['date'], '%Y-%m-%d').date()
            except ValueError:
                raise CommandError(f'--date 형식이 잘못됐습니다: {options["date"]} (YYYY-MM-DD)')

        reference, problems, status = run(today)

        if not options['quiet']:
            self.print_table(reference, status)

        self.log.separator()
        # '오류: N개' 는 배치가 출력에서 집어내는 공통 관례다 (batch_lib.sh).
        if problems:
            self.log.info(f'완료 | 점검 {len(status)}개, 오류: {len(problems)}개',
                          success=True)
            self.log.info('')
            self.log.info('[오류 목록]')
            for p in problems:
                self.log.error(f'  {p}')
            # 종료코드로 끝낸다. 이 명령 자체가 '조용한 고장' 을 잡으려고
            # 있는 것이라, 자기가 조용히 끝나면 뜻이 없다.
            raise CommandError(f'신선하지 않은 데이터 {len(problems)}건')

        self.log.info(f'완료 | 점검 {len(status)}개, 모두 정상 (기준 {reference})',
                      success=True)

    def print_table(self, reference, status):
        self.log.info(f'기준일 {reference} '
                      f'(가장 앞선 데이터. 전체 지각 한도 {MAX_LAG_BUSINESS_DAYS}영업일)')
        self.log.separator()
        self.log.info(f'{"항목":14s} {"최신일":12s} {"상태":>12s}')
        for s in status:
            # 신선도 항목은 check 를, 정체·교차 항목은 label 을 들고 온다.
            label = s['check'].label if 'check' in s else s['label']
            if 'note' in s:
                mark = s['note']
            else:
                behind = s.get('behind')
                mark = ('데이터 없음' if behind is None
                        else '-' if behind == 0 else f'{behind}영업일')
            shown = str(s['overall']) if s['overall'] else ''
            self.log.info(f'  {label:12s} {shown:12s} {mark:>12s}')
            # 그룹이 서로 어긋날 때만 펼친다. 같으면 줄만 늘어난다.
            groups = s.get('groups') or {}
            if len(set(groups.values())) > 1:
                for name, d in sorted(groups.items()):
                    self.log.info(f'      └ {name:10s} {d}')
