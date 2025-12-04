import time
import requests
from datetime import datetime
from django.core.management.base import BaseCommand
from stocks.models import Info, Report
from stocks.logger import StockLogger


class Command(BaseCommand):
    help = '애널리스트 리포트 조회 및 저장 (FnGuide)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--code',
            type=str,
            required=True,
            help='종목코드 또는 "all" (전체 종목, ETF 제외)'
        )
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        # 로거 초기화
        self.log = StockLogger(self.stdout, self.style, options, 'save_report')

        # stdout 버퍼링 비활성화
        import sys
        sys.stdout.reconfigure(line_buffering=True)

        code = options['code']
        process_all = code.lower() == 'all'

        if process_all:
            self.process_all_stocks()
        else:
            self.process_single_stock(code)

    def process_single_stock(self, stock_code):
        """단일 종목 처리"""
        try:
            stock = Info.objects.get(code=stock_code)
            self.log.info(f'종목: {stock.name} ({stock_code})')
        except Info.DoesNotExist:
            self.log.error(f'종목 정보 없음: {stock_code}')
            return

        self.log.separator()
        result = self.fetch_and_save(stock)
        if result:
            self.log.info(result, success=True)

    def process_all_stocks(self):
        """전체 종목 처리 (ETF 제외, is_active=True)"""
        stocks = Info.objects.filter(
            is_active=True
        ).exclude(
            market='ETF'
        ).values_list('code', 'name')

        total_count = stocks.count()
        self.log.info(f'리포트 조회 시작 ({total_count}개 종목, ETF 제외)')

        success_count = 0
        no_data_list = []
        error_list = []

        for idx, (code, name) in enumerate(stocks, 1):
            try:
                stock = Info.objects.get(code=code)
                result = self.fetch_and_save(stock, silent=True)

                if result:
                    self.log.info(f'[{idx}/{total_count}] {code} {name}: {result}')
                    success_count += 1
                else:
                    self.log.info(f'[{idx}/{total_count}] {code} {name}: 데이터 없음')
                    no_data_list.append((code, name))

                # API 호출 간격 (0.2초)
                time.sleep(0.2)

            except Exception as e:
                self.log.error(f'[{idx}/{total_count}] {code} {name}: 처리 실패 - {str(e)}')
                error_list.append((code, name, str(e)))

        # 최종 리포트
        self.log.separator()
        self.log.info(f'리포트 조회 완료: 성공 {success_count}개, 데이터없음 {len(no_data_list)}개, 오류 {len(error_list)}개', success=True)

        if no_data_list:
            self.log.info(f'[데이터 없음] {len(no_data_list)}개:')
            for code, name in no_data_list[:20]:
                self.log.info(f'  - {code} {name}')
            if len(no_data_list) > 20:
                self.log.info(f'  ... 외 {len(no_data_list) - 20}개')

        if error_list:
            self.log.info(f'[오류 발생] {len(error_list)}개:')
            for code, name, err in error_list:
                self.log.error(f'  - {code} {name}: {err}')

    def fetch_and_save(self, stock, silent=False):
        """리포트 조회 및 저장"""
        reports = self.fetch_reports(stock.code)

        if not reports:
            return None

        created_count = 0
        skipped_count = 0

        for report in reports:
            try:
                # 날짜 파싱 (25/12/03 -> 2025-12-03)
                date_str = report.get('ANL_DT', '')
                if not date_str:
                    continue
                date = datetime.strptime(date_str, '%y/%m/%d').date()

                title = report.get('RPT_TITLE', '')
                if not title:
                    continue

                # 날짜 + 제목으로 중복 체크
                exists = Report.objects.filter(
                    stock=stock,
                    date=date,
                    title=title
                ).exists()

                if exists:
                    skipped_count += 1
                    continue

                # 목표가 파싱 (160,000 -> 160000)
                target_price_str = report.get('TARGET_PRC', '')
                target_price = None
                if target_price_str:
                    try:
                        target_price = int(target_price_str.replace(',', ''))
                    except (ValueError, TypeError):
                        pass

                # 저장
                Report.objects.create(
                    stock=stock,
                    report_id=report.get('RPT_ID'),
                    date=date,
                    title=title,
                    author=report.get('ANL_NM_KOR', ''),
                    provider=report.get('BRK_NM_KOR', ''),
                    target_price=target_price,
                    recommendation=report.get('RECOMM', ''),
                )
                created_count += 1

            except Exception as e:
                if not silent:
                    self.log.error(f'저장 실패: {str(e)}')

        if created_count > 0 or skipped_count > 0:
            return f'신규 {created_count}, 스킵 {skipped_count}'
        return None

    def fetch_reports(self, code):
        """FnGuide API에서 리포트 조회 (첫 페이지)"""
        url = 'https://comp.wisereport.co.kr/company/ajax/c1080001_data.aspx'
        params = {
            'cmp_cd': code,
            'cnt': 20,
            'page': 1,
        }
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': f'https://comp.wisereport.co.kr/company/c1080001.aspx?cmp_cd={code}',
        }

        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get('lists', [])

        except Exception as e:
            self.log.debug(f'API 호출 실패: {e}')
            return []
