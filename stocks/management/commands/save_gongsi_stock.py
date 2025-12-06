import time
import re
from datetime import datetime
from django.core.management.base import BaseCommand
from stocks.models import Info, Gongsi
from stocks.logger import StockLogger


class Command(BaseCommand):
    help = '''
DART 공시 조회 및 저장

옵션:
  --code      (필수*) 종목코드 또는 "all" / "fav"
              - all: 전체 종목
              - fav: 관심 종목만 (interest_level 설정된 종목)
  --clear     (선택) 전체 데이터 삭제
  --log-level (선택) debug / info / warning / error (기본값: info)

  * --clear 사용 시 --code 불필요

예시:
  python manage.py save_gongsi_stock --code 005930
  python manage.py save_gongsi_stock --code all --log-level info
  python manage.py save_gongsi_stock --code fav
  python manage.py save_gongsi_stock --clear
'''

    def add_arguments(self, parser):
        parser.add_argument(
            '--code',
            type=str,
            help='종목코드 또는 "all" (전체 종목)'
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='전체 데이터 삭제'
        )
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        # --clear 옵션 처리
        if options.get('clear'):
            deleted_count, _ = Gongsi.objects.all().delete()
            self.stdout.write(self.style.SUCCESS(f'Gongsi 데이터 {deleted_count}건 삭제 완료'))
            return

        # 필수 옵션 체크
        if not options.get('code'):
            self.print_help('manage.py', 'save_gongsi_stock')
            return

        # 로거 초기화
        self.log = StockLogger(self.stdout, self.style, options, 'save_gongsi_stock')

        # stdout 버퍼링 비활성화
        import sys
        sys.stdout.reconfigure(line_buffering=True)

        code = options['code'].lower()

        if code == 'all':
            self.process_stocks(fav_only=False)
        elif code == 'fav':
            self.process_stocks(fav_only=True)
        else:
            self.process_single_stock(options['code'])

    def process_single_stock(self, stock_code):
        """단일 종목 처리"""
        try:
            stock = Info.objects.get(code=stock_code)
            self.log.info(f'종목: {stock.name}({stock_code})')
        except Info.DoesNotExist:
            self.log.error(f'종목 정보 없음: {stock_code}')
            return

        self.log.separator()
        result = self.fetch_and_save(stock)
        self.log.separator()
        if result:
            self.log.info(f'완료 | {result}', success=True)
        else:
            self.log.info('완료 | 데이터 없음', success=True)

    def process_stocks(self, fav_only=False):
        """종목 처리"""
        stocks = Info.objects.filter(is_active=True)

        if fav_only:
            stocks = stocks.filter(interest_level__isnull=False)
            mode = '관심 종목'
        else:
            mode = '전체 종목'

        stocks = stocks.values_list('code', 'name')
        total_count = stocks.count()
        self.log.info(f'DART 공시 저장 시작 (대상: {mode} {total_count}개)')

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

                # Playwright 호출 간격 (2초)
                time.sleep(2)

            except Exception as e:
                self.log.error(f'[{idx}/{total_count}] {code} {name}: 처리 실패 - {str(e)}')
                error_list.append((code, name, str(e)))

        # 최종 리포트
        self.log.separator()
        if error_list:
            self.log.info(f'완료 | 성공: {success_count}개, 데이터없음: {len(no_data_list)}개, 오류: {len(error_list)}개', success=True)
            self.log.info('')
            self.log.info('[오류 목록]')
            for code, name, err in error_list:
                self.log.error(f'  {code} {name}: {err}')
        elif no_data_list:
            self.log.info(f'완료 | 성공: {success_count}개, 데이터없음: {len(no_data_list)}개', success=True)
        else:
            self.log.info(f'완료 | 성공: {success_count}개', success=True)

    def fetch_and_save(self, stock, silent=False):
        """DART 공시 조회 및 저장"""
        disclosures = self.fetch_dart(stock.code)

        if not disclosures:
            return None

        created_count = 0
        skipped_count = 0

        for disclosure in disclosures:
            try:
                title = disclosure.get('title', '')
                link = disclosure.get('link', '')

                if not title or not link:
                    continue

                # 링크로 중복 체크
                exists = Gongsi.objects.filter(link=link).exists()

                if exists:
                    skipped_count += 1
                    continue

                # 날짜 파싱 (예: "2024.12.03" -> date)
                date_str = disclosure.get('date', '')
                date = self.parse_date(date_str)

                # 저장
                Gongsi.objects.create(
                    stock=stock,
                    date=date,
                    title=title,
                    link=link,
                    submitter=disclosure.get('submitter', ''),
                )
                created_count += 1

            except Exception as e:
                if not silent:
                    self.log.error(f'저장 실패: {str(e)}')

        if created_count > 0 or skipped_count > 0:
            return f'신규 {created_count}, 스킵 {skipped_count}'
        return None

    def parse_date(self, date_str):
        """날짜 문자열 파싱"""
        if not date_str:
            return None

        # "2024.12.03", "2024-12-03", "24.12.03" 등 다양한 형식 처리
        date_str = date_str.strip()

        # 숫자만 추출
        numbers = re.findall(r'\d+', date_str)
        if len(numbers) >= 3:
            year, month, day = numbers[0], numbers[1], numbers[2]
            # 2자리 연도 처리
            if len(year) == 2:
                year = '20' + year
            try:
                return datetime(int(year), int(month), int(day)).date()
            except ValueError:
                pass

        return None

    def fetch_dart(self, code):
        """DART 공시 조회 (Playwright 사용)"""
        try:
            from playwright.sync_api import sync_playwright
            from bs4 import BeautifulSoup
        except ImportError as e:
            self.log.error(f'필수 모듈 없음: {e}')
            return []

        url = f'https://dart.fss.or.kr/html/search/SearchCompany_M2.html?textCrpNM={code}'

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, wait_until='domcontentloaded', timeout=60000)
                page.wait_for_timeout(5000)

                html = page.content()
                browser.close()

                soup = BeautifulSoup(html, 'html.parser')
                table = soup.select_one('table')
                rows = table.select('tbody tr') if table else []

                results = []
                for row in rows[:30]:  # 최대 30개
                    cells = row.select('td')
                    if len(cells) >= 5:
                        report_el = cells[2].select_one('a')
                        report_name = report_el.get_text(strip=True) if report_el else ''
                        report_link = report_el.get('href', '') if report_el else ''

                        if report_link and not report_link.startswith('http'):
                            report_link = 'https://dart.fss.or.kr' + report_link

                        results.append({
                            'date': cells[4].get_text(strip=True),
                            'title': report_name,
                            'link': report_link,
                            'submitter': cells[3].get_text(strip=True),
                        })

                return results

        except Exception as e:
            self.log.debug(f'Playwright 에러: {e}')
            return []
