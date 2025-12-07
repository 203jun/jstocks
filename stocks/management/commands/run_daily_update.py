"""
일일 데이터 업데이트 (순차 실행)

장 마감 후 실행하며, 모든 일일 업데이트 명령어를 순차적으로 실행합니다.

사용법:
  python manage.py run_daily_update
  python manage.py run_daily_update --log-level debug
"""

from django.core.management.base import BaseCommand
from django.core.management import call_command
from stocks.logger import StockLogger


class Command(BaseCommand):
    help = '일일 데이터 업데이트 (순차 실행)'

    def add_arguments(self, parser):
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        self.log = StockLogger(self.stdout, self.style, options, 'run_daily_update')

        tasks = [
            # (명령어, kwargs, 설명)
            ('save_index_chart', {'mode': 'last'}, '지수 차트'),
            ('save_market_trend', {'mode': 'last'}, '시장 동향'),
            ('save_sector', {'mode': 'last'}, '업종'),
            ('save_stock_info', {'code': 'all'}, '종목 기본정보'),
            ('save_daily_chart', {'code': 'all', 'mode': 'last'}, '일봉 차트'),
            ('save_weekly_chart', {'code': 'all', 'mode': 'last'}, '주봉 차트'),
            ('save_monthly_chart', {'code': 'all', 'mode': 'last'}, '월봉 차트'),
            ('save_investor_trend', {'code': 'fav', 'mode': 'last'}, '투자자 매매동향'),
            ('save_short_selling', {'code': 'fav', 'mode': 'last'}, '공매도'),
            ('save_gongsi_stock', {'code': 'fav'}, '공시'),
            ('save_fnguide_report', {'code': 'fav'}, '리포트'),
            ('save_nodaji_stock', {'code': 'fav'}, '노다지'),
            ('save_etf_chart', {'mode': 'last'}, 'ETF 차트'),
        ]

        total = len(tasks)
        success_count = 0
        error_list = []

        self.log.info(f'일일 업데이트 시작 (총 {total}개 작업)')
        self.log.separator()

        for idx, (cmd, kwargs, desc) in enumerate(tasks, 1):
            try:
                self.log.info(f'[{idx}/{total}] {desc}...')
                call_command(cmd, **kwargs)
                success_count += 1
            except Exception as e:
                self.log.error(f'  실패: {str(e)}')
                error_list.append((desc, str(e)))

        self.log.separator()
        if error_list:
            self.log.info(f'완료 | 성공: {success_count}개, 실패: {len(error_list)}개', success=True)
            self.log.info('')
            self.log.info('[실패 목록]')
            for desc, err in error_list:
                self.log.error(f'  {desc}: {err}')
        else:
            self.log.info(f'완료 | 성공: {success_count}개', success=True)
