import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from stocks.logger import StockLogger


class Command(BaseCommand):
    help = '네이버 금융 외국인/기관 수급 크롤링'

    def add_arguments(self, parser):
        parser.add_argument(
            '--code',
            type=str,
            default='005930',
            help='종목코드 (기본값: 005930 - 삼성전자)'
        )
        parser.add_argument(
            '--mode',
            type=str,
            choices=['all', 'day'],
            default='day',
            help='크롤링 모드: all(1~6페이지 전체), day(최근 1일만)'
        )
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        # 로거 초기화
        self.log = StockLogger(self.stdout, self.style, options, 'crawl_naver_investor')

        stock_code = options['code']
        mode = options['mode']

        self.log.info(f'종목코드: {stock_code} | 모드: {mode}')
        self.log.separator()

        if mode == 'all':
            # 1~6페이지 전체 크롤링
            self.crawl_all_pages(stock_code)
        elif mode == 'day':
            # 최근 1일만 크롤링
            self.crawl_latest_day(stock_code)

        self.log.info('크롤링 완료!', success=True)

    def crawl_all_pages(self, stock_code):
        """1~6페이지 전체 크롤링"""
        for page_num in range(1, 7):
            self.log.header(f'페이지 {page_num}')

            data = self.crawl_page(stock_code, page_num)

            if data:
                self.log.debug(f"날짜\t\t| 기관 순매수\t| 외국인 순매수")
                self.log.debug('-' * 70)

                for item in data:
                    self.log.debug(
                        f"{item['date']}\t| {item['institution']:>12}\t| {item['foreign']:>12}"
                    )
            else:
                self.log.warning(f'페이지 {page_num} 데이터 없음')

    def crawl_latest_day(self, stock_code):
        """최근 1일만 크롤링"""
        self.log.header('최근 1일 데이터')

        data = self.crawl_page(stock_code, 1)

        if data and len(data) > 0:
            # 첫 번째 데이터만 가져오기
            item = data[0]
            self.log.debug(f"날짜\t\t| 기관 순매수\t| 외국인 순매수")
            self.log.debug('-' * 70)
            self.log.debug(
                f"{item['date']}\t| {item['institution']:>12}\t| {item['foreign']:>12}"
            )
        else:
            self.log.warning('데이터 없음')

    def crawl_page(self, stock_code, page_num):
        """네이버 금융 페이지 크롤링"""
        url = f'https://finance.naver.com/item/frgn.naver?code={stock_code}&page={page_num}'

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.encoding = 'euc-kr'  # 네이버 금융은 euc-kr 인코딩

            soup = BeautifulSoup(response.text, 'html.parser')

            # 날짜별 데이터 테이블
            tables = soup.find_all('table', {'class': 'type2'})

            if len(tables) >= 2:
                table = tables[1]
                rows = table.find_all('tr')

                result = []

                for row in rows:
                    cols = row.find_all('td')

                    # 9개 컬럼이 있는 데이터 행만 처리
                    if len(cols) == 9:
                        date = cols[0].get_text(strip=True)
                        institution = cols[5].get_text(strip=True)  # 기관 순매매량
                        foreign = cols[6].get_text(strip=True)  # 외국인 순매매량

                        result.append({
                            'date': date,
                            'institution': institution,
                            'foreign': foreign,
                        })

                return result
            else:
                return None

        except Exception as e:
            self.log.error(f'크롤링 실패: {str(e)}')
            return None
