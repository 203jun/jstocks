import re
import time
from decimal import Decimal, InvalidOperation
import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from stocks.models import Info, Financial
from stocks.logger import StockLogger


# 월 -> 분기 매핑
MONTH_TO_QUARTER = {
    '03': '1Q',
    '06': '2Q',
    '09': '3Q',
    '12': '4Q',
}


class Command(BaseCommand):
    help = '재무제표 데이터 크롤링 및 저장 (네이버 금융)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--code',
            type=str,
            required=True,
            help='종목코드 또는 "all" (전체 종목)'
        )
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        self.log = StockLogger(self.stdout, self.style, options, 'save_financial_naver')
        stock_code = options['code']

        if stock_code.lower() == 'all':
            self.process_all_stocks()
        else:
            self.process_single_stock(stock_code)

    def process_single_stock(self, stock_code):
        """단일 종목 처리"""
        try:
            info = Info.objects.get(code=stock_code)
        except Info.DoesNotExist:
            self.log.error(f'종목코드 {stock_code}가 Info에 없습니다.')
            return

        self.log.info(f'{info.name}({stock_code}) 네이버 금융 크롤링 시작...')

        data = self.crawl_naver_finance(stock_code)
        if not data:
            self.log.error('크롤링 실패')
            return

        self.save_to_db(info, data)

    def process_all_stocks(self):
        """전체 종목 처리"""
        stocks = Info.objects.filter(is_active=True).exclude(market='ETF').values_list('code', 'name')
        total = len(stocks)

        self.log.info(f'전체 {total}개 종목 처리 시작...')

        success_count = 0
        error_count = 0
        error_codes = []

        for idx, (code, name) in enumerate(stocks, 1):
            try:
                data = self.crawl_naver_finance(code)
                if data:
                    info = Info.objects.get(code=code)
                    saved, updated, skipped = self.save_to_db(info, data, silent=True)
                    self.log.info(f'[{idx}/{total}] {name}({code}): 신규 {saved}, 업데이트 {updated}, 스킵 {skipped}')
                    success_count += 1
                else:
                    self.log.info(f'[{idx}/{total}] {name}({code}): 데이터 없음')
                    error_count += 1
                    error_codes.append(code)
            except Exception as e:
                self.log.error(f'[{idx}/{total}] {name}({code}): 실패 - {e}')
                error_count += 1
                error_codes.append(code)

            # 요청 간격 (네이버 차단 방지)
            time.sleep(0.3)

        self.log.info(f'처리 완료: 성공 {success_count}개, 실패 {error_count}개', success=True)
        if error_codes:
            self.log.error(f'실패 종목: {", ".join(error_codes[:20])}{"..." if len(error_codes) > 20 else ""}')

    def crawl_naver_finance(self, stock_code):
        """네이버 금융에서 재무제표 테이블 크롤링"""
        url = f'https://finance.naver.com/item/main.naver?code={stock_code}'
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
        except Exception as e:
            self.log.error(f'HTTP 요청 실패: {e}')
            return None

        soup = BeautifulSoup(response.text, 'lxml')
        table = soup.select_one('#content > div.section.cop_analysis > div.sub_section > table')

        if not table:
            self.log.error('테이블을 찾을 수 없습니다.')
            return None

        # 헤더 파싱
        headers = [th.get_text(strip=True) for th in table.select('thead th')]

        # 연간/분기 컬럼 인덱스 찾기
        # 헤더 구조: [주요재무정보, 최근 연간 실적, 최근 분기 실적, 연간1, 연간2, 연간3, 연간4, 분기1, 분기2, ...]
        # 연간: 인덱스 3~6 (4개)
        # 분기: 인덱스 7~12 (6개)
        annual_columns = []  # (index, year, is_estimated)
        quarterly_columns = []  # (index, year, quarter, is_estimated)

        annual_start = 3
        annual_end = 7  # exclusive
        quarterly_start = 7
        quarterly_end = 13  # exclusive

        for idx in range(annual_start, min(annual_end, len(headers))):
            parsed = self.parse_header(headers[idx])
            if parsed:
                year, quarter, is_estimated = parsed
                annual_columns.append((idx, year, is_estimated))

        for idx in range(quarterly_start, min(quarterly_end, len(headers))):
            parsed = self.parse_header(headers[idx])
            if parsed:
                year, quarter, is_estimated = parsed
                quarterly_columns.append((idx, year, quarter, is_estimated))

        # 데이터 행 파싱
        row_data = {}
        for tr in table.select('tbody tr'):
            row_header = tr.select_one('th')
            cells = tr.select('td')
            if row_header:
                row_name = row_header.get_text(strip=True)
                values = [td.get_text(strip=True) for td in cells]
                row_data[row_name] = values

        return {
            'annual_columns': annual_columns,
            'quarterly_columns': quarterly_columns,
            'row_data': row_data,
        }

    def parse_header(self, header):
        """헤더 파싱: '2025.12(E)' -> (2025, '4Q', True)"""
        # 연간: 2024.12, 2025.12(E)
        # 분기: 2024.09, 2025.03(E)
        match = re.match(r'(\d{4})\.(\d{2})(\(E\))?', header)
        if not match:
            return None

        year = int(match.group(1))
        month = match.group(2)
        is_estimated = match.group(3) is not None

        quarter = MONTH_TO_QUARTER.get(month)
        if not quarter:
            return None

        return year, quarter, is_estimated

    def parse_value(self, value):
        """값 파싱: '3,022,314' -> 3022314"""
        if not value or value == '-' or value == '':
            return None
        try:
            # 쉼표 제거
            cleaned = value.replace(',', '')
            return int(cleaned)
        except (ValueError, TypeError):
            return None

    def parse_decimal(self, value):
        """소수점 값 파싱: '14.35' -> Decimal('14.35')"""
        if not value or value == '-' or value == '':
            return None
        try:
            return Decimal(value)
        except InvalidOperation:
            return None

    def save_to_db(self, info, data, silent=False):
        """크롤링 데이터를 DB에 저장"""
        annual_columns = data['annual_columns']
        quarterly_columns = data['quarterly_columns']
        row_data = data['row_data']

        saved_count = 0
        updated_count = 0
        skipped_count = 0

        # 연간 데이터 저장
        for idx, year, is_estimated in annual_columns:
            result = self.save_financial_record(
                info=info,
                year=year,
                quarter=None,
                is_estimated=is_estimated,
                row_data=row_data,
                col_idx=idx - 3,  # 헤더 오프셋 조정 (첫 3개는 헤더)
            )
            if result == 'created':
                saved_count += 1
            elif result == 'updated':
                updated_count += 1
            elif result == 'skipped':
                skipped_count += 1

        # 분기 데이터 저장
        for idx, year, quarter, is_estimated in quarterly_columns:
            result = self.save_financial_record(
                info=info,
                year=year,
                quarter=quarter,
                is_estimated=is_estimated,
                row_data=row_data,
                col_idx=idx - 3,  # 헤더 오프셋 조정
            )
            if result == 'created':
                saved_count += 1
            elif result == 'updated':
                updated_count += 1
            elif result == 'skipped':
                skipped_count += 1

        if not silent:
            self.log.info(f'{info.name}({info.code}) 저장 완료: 신규 {saved_count}건, 업데이트 {updated_count}건, 스킵 {skipped_count}건', success=True)

        return saved_count, updated_count, skipped_count

    def save_financial_record(self, info, year, quarter, is_estimated, row_data, col_idx):
        """개별 재무 레코드 저장"""
        # 값 추출
        revenue = self.parse_value(row_data.get('매출액', [])[col_idx] if col_idx < len(row_data.get('매출액', [])) else None)
        operating_profit = self.parse_value(row_data.get('영업이익', [])[col_idx] if col_idx < len(row_data.get('영업이익', [])) else None)
        net_income = self.parse_value(row_data.get('당기순이익', [])[col_idx] if col_idx < len(row_data.get('당기순이익', [])) else None)
        operating_margin = self.parse_decimal(row_data.get('영업이익률', [])[col_idx] if col_idx < len(row_data.get('영업이익률', [])) else None)
        net_margin = self.parse_decimal(row_data.get('순이익률', [])[col_idx] if col_idx < len(row_data.get('순이익률', [])) else None)
        roe = self.parse_decimal(row_data.get('ROE(지배주주)', [])[col_idx] if col_idx < len(row_data.get('ROE(지배주주)', [])) else None)

        # 네이버는 억 단위 -> 원 단위로 변환 (억 * 1억)
        if revenue:
            revenue = revenue * 100000000
        if operating_profit:
            operating_profit = operating_profit * 100000000
        if net_income:
            net_income = net_income * 100000000

        new_data = {
            'revenue': revenue,
            'operating_profit': operating_profit,
            'net_income': net_income,
            'operating_margin': operating_margin,
            'net_margin': net_margin,
            'roe': roe,
            'is_estimated': is_estimated,
        }

        # 기존 레코드 조회
        try:
            existing = Financial.objects.get(stock=info, year=year, quarter=quarter)

            # 값 비교 (변경된 경우에만 업데이트)
            has_changes = False
            for field, new_val in new_data.items():
                old_val = getattr(existing, field)
                if old_val != new_val:
                    has_changes = True
                    break

            if has_changes:
                for field, new_val in new_data.items():
                    setattr(existing, field, new_val)
                existing.save()
                return 'updated'
            else:
                return 'skipped'

        except Financial.DoesNotExist:
            # 신규 생성
            Financial.objects.create(
                stock=info,
                year=year,
                quarter=quarter,
                **new_data
            )
            return 'created'
