import time
import re
from datetime import datetime
from django.core.management.base import BaseCommand
from stocks.models import Info, Nodaji
from stocks.logger import StockLogger


class Command(BaseCommand):
    help = '''
노다지 IR노트 기사 조회 및 저장 (네이버 프리미엄 콘텐츠)

옵션:
  --code      (필수*) 종목코드 또는 "all" / "fav"
              - all: 전체 종목
              - fav: 관심 종목만 (interest_level 설정된 종목)
  --clear     (선택) 전체 데이터 삭제
  --log-level (선택) debug / info / warning / error (기본값: info)

  * --clear 사용 시 --code 불필요

예시:
  python manage.py save_nodaji_stock --code 005930
  python manage.py save_nodaji_stock --code all --log-level info
  python manage.py save_nodaji_stock --code fav
  python manage.py save_nodaji_stock --clear
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
            deleted_count, _ = Nodaji.objects.all().delete()
            self.stdout.write(self.style.SUCCESS(f'Nodaji 데이터 {deleted_count}건 삭제 완료'))
            return

        # 필수 옵션 체크
        if not options.get('code'):
            self.print_help('manage.py', 'save_nodaji_stock')
            return

        # 로거 초기화
        self.log = StockLogger(self.stdout, self.style, options, 'save_nodaji_stock')

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
        self.log.info(f'노다지 기사 저장 시작 (대상: {mode} {total_count}개)')

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

                # Playwright 호출 간격 (1초)
                time.sleep(1)

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
        """노다지 기사 조회 및 저장"""
        articles = self.fetch_nodaji(stock.name)

        if not articles:
            return None

        created_count = 0
        skipped_count = 0

        for article in articles:
            try:
                title = article.get('title', '')
                link = article.get('link', '')

                if not title or not link:
                    continue

                # 링크로 중복 체크
                exists = Nodaji.objects.filter(link=link).exists()

                if exists:
                    skipped_count += 1
                    continue

                # 날짜 파싱 (예: "2024.12.03" -> date)
                date_str = article.get('date', '')
                date = self.parse_date(date_str)

                # 저장
                Nodaji.objects.create(
                    stock=stock,
                    date=date,
                    title=title,
                    link=link,
                    summary='',  # 요약은 나중에 추가
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

    def fetch_nodaji(self, keyword):
        """노다지 검색 (Playwright 사용)"""
        try:
            from playwright.sync_api import sync_playwright
            from bs4 import BeautifulSoup
        except ImportError as e:
            self.log.error(f'필수 모듈 없음: {e}')
            return []

        url = f'https://contents.premium.naver.com/ystreet/irnote/search?searchQuery={keyword}'

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, wait_until='networkidle')

                # 페이지 로드 대기 및 스크롤
                page.wait_for_timeout(3000)
                page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                page.wait_for_timeout(2000)

                html = page.content()
                browser.close()

                # HTML 파싱
                soup = BeautifulSoup(html, 'html.parser')
                results = []
                cards = soup.select('.psp_content_item')

                for card in cards[:20]:
                    # 제목
                    title_el = card.select_one('strong.psp_name')
                    title = title_el.get_text(strip=True) if title_el else ''

                    # 날짜
                    date_el = card.select_one('.psp_content_info_text')
                    date = date_el.get_text(strip=True) if date_el else ''

                    # 링크
                    link_el = card.select_one('a.psp_content_link')
                    link = ''
                    if link_el and link_el.get('href'):
                        link = link_el.get('href')
                        if not link.startswith('http'):
                            link = 'https://contents.premium.naver.com' + link

                    if title:
                        results.append({
                            'title': title,
                            'date': date,
                            'link': link,
                        })

                return results

        except Exception as e:
            self.log.debug(f'Playwright 에러: {e}')
            return []
