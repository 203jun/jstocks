import os
import re
import math
import unicodedata
from decimal import Decimal, InvalidOperation
import pandas as pd
from django.core.management.base import BaseCommand
from stocks.models import Info, Financial
from stocks.logger import StockLogger


# 분기별 컬럼 정의
QUARTER_CONFIG = {
    '1Q': {'column': '당기 1분기 3개월'},
    '2Q': {'column': '당기 반기 3개월'},
    '3Q': {'column': '당기 3분기 3개월'},
    '4Q': {'column': '당기'},
}

# 보고서 종류 -> 분기 매핑
REPORT_TO_QUARTER = {
    '1분기보고서': '1Q',
    '반기보고서': '2Q',
    '3분기보고서': '3Q',
    '사업보고서': '4Q',
}

# 항목코드 매칭 규칙
ITEM_CODES = {
    '매출액': 'ifrs-full_Revenue',
    '영업이익': 'dart_OperatingIncomeLoss',
    '순이익': 'ifrs-full_ProfitLoss',
}


class Command(BaseCommand):
    help = '재무제표 초기 데이터 로드 (jemu 폴더 txt 파일) - 최초 1회 실행'

    def add_arguments(self, parser):
        # 종목 선택 (종목코드 또는 'all')
        parser.add_argument(
            '--code',
            type=str,
            help='종목코드 또는 "all" (전체 종목, ETF 제외)'
        )
        # 데이터 유형 (--mode: annual/quarterly/all)
        parser.add_argument(
            '--mode',
            type=str,
            choices=['annual', 'quarterly', 'all'],
            default='all',
            help='데이터 유형 (annual: 연간, quarterly: 분기, all: 둘 다, 기본값: all)'
        )
        # 기존 데이터 삭제
        parser.add_argument(
            '--clear',
            action='store_true',
            help='기존 Financial 데이터 전체 삭제'
        )
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        self.log = StockLogger(self.stdout, self.style, options, 'init_financial')

        clear = options['clear']
        code = options['code']

        # 옵션 검증: --clear와 --code는 동시 사용 불가
        if clear and code:
            self.log.error('--clear와 --code는 동시에 사용할 수 없습니다.')
            return

        if not clear and not code:
            self.log.error('--clear 또는 --code 옵션이 필요합니다.')
            return

        # --clear 옵션: 기존 데이터 삭제 후 종료
        if clear:
            deleted_count, _ = Financial.objects.all().delete()
            self.log.info(f'Financial 데이터 {deleted_count}건 삭제 완료', success=True)
            return

        mode = options['mode']
        process_all = code.lower() == 'all'

        # mode에 따라 처리할 데이터 유형 결정
        do_annual = mode in ['annual', 'all']
        do_quarterly = mode in ['quarterly', 'all']

        # jemu 폴더 경로 (프로젝트 루트/jemu)
        from django.conf import settings
        jemu_path = os.path.join(settings.BASE_DIR, 'jemu')

        # 포괄손익계산서 파일 목록 (macOS NFD 정규화 처리)
        comprehensive_files = sorted([
            f for f in os.listdir(jemu_path)
            if f.endswith('.txt') and '포괄손익계산서' in unicodedata.normalize('NFC', f)
        ])

        if process_all:
            # 전체 종목 처리 (ETF 제외)
            self.process_all_stocks(jemu_path, comprehensive_files, do_annual, do_quarterly)
        else:
            # 단일 종목 처리
            self.process_single_stock(jemu_path, comprehensive_files, code, do_annual, do_quarterly)

    def process_single_stock(self, jemu_path, comprehensive_files, stock_code, do_annual, do_quarterly):
        """단일 종목 처리"""
        # 재무 데이터 수집
        financial_data = []
        for filename in comprehensive_files:
            data = self.extract_financial_data(jemu_path, filename, stock_code)
            if data:
                financial_data.append(data)

        # 연도/분기 순으로 정렬
        financial_data.sort(key=lambda x: (x['year'], x['quarter']))

        if do_annual:
            # 연간 데이터: 4Q 원본 데이터 (보정 전) 사용
            annual_data = self.get_annual_data(financial_data)
            self.print_financial_table(stock_code, annual_data, is_annual=True)
            self.save_to_db(stock_code, annual_data, is_annual=True)

        if do_quarterly:
            # 분기 데이터: 4Q 보정 적용
            quarterly_data = self.adjust_4q_data(financial_data.copy())
            self.print_financial_table(stock_code, quarterly_data, is_annual=False)
            self.save_to_db(stock_code, quarterly_data, is_annual=False)

    def process_all_stocks(self, jemu_path, comprehensive_files, do_annual, do_quarterly):
        """전체 종목 일괄 처리 (ETF 제외)"""
        # KOSPI, KOSDAQ만 조회 (ETF 제외)
        stocks = Info.objects.filter(
            is_active=True
        ).exclude(
            market='ETF'
        ).values_list('code', 'name', 'market')

        total_count = stocks.count()
        data_types = []
        if do_annual:
            data_types.append('연간')
        if do_quarterly:
            data_types.append('분기')
        self.log.info(f'재무제표 초기 데이터 로드 시작 ({"/".join(data_types)}, {total_count}개 종목, ETF 제외)')

        success_count = 0
        no_data_count = 0
        error_codes = []

        for idx, (code, name, market) in enumerate(stocks, 1):
            self.log.debug(f'[{idx}/{total_count}] {code} {name} ({market}) 처리 중...')

            try:
                # 재무 데이터 수집
                financial_data = []
                for filename in comprehensive_files:
                    data = self.extract_financial_data(jemu_path, filename, code)
                    if data:
                        financial_data.append(data)

                if not financial_data:
                    self.log.info(f'[{idx}/{total_count}] {code} {name}: 데이터 없음')
                    no_data_count += 1
                    continue

                # 연도/분기 순으로 정렬
                financial_data.sort(key=lambda x: (x['year'], x['quarter']))

                results = []

                if do_annual:
                    annual_data = self.get_annual_data(financial_data)
                    if annual_data:
                        saved, updated = self.save_to_db_silent(code, annual_data, is_annual=True)
                        results.append(f'연간 {len(annual_data)}건')

                if do_quarterly:
                    quarterly_data = self.adjust_4q_data(financial_data.copy())
                    if quarterly_data:
                        saved, updated = self.save_to_db_silent(code, quarterly_data, is_annual=False)
                        results.append(f'분기 {len(quarterly_data)}건')

                if results:
                    self.log.info(f'[{idx}/{total_count}] {code} {name}: {", ".join(results)}')
                    success_count += 1

            except Exception as e:
                self.log.error(f'[{idx}/{total_count}] {code} {name}: 처리 실패 - {str(e)}')
                error_codes.append(code)

        # 최종 요약
        error_count = len(error_codes)
        summary = f'재무제표 초기 데이터 로드 완료: 성공 {success_count}개, 데이터없음 {no_data_count}개, 오류 {error_count}개'
        if error_codes:
            summary += f' ({", ".join(error_codes)})'
        self.log.info(summary, success=True)

    def save_to_db_silent(self, stock_code, financial_data, is_annual=False):
        """재무 데이터를 DB에 저장 (신규/업데이트 카운트 반환)"""
        info = Info.objects.get(code=stock_code)
        saved_count = 0
        updated_count = 0

        for idx, data in enumerate(financial_data):
            year = data['year']
            quarter = None if is_annual else data['quarter']

            # 증가율 계산
            prev_data = self.get_previous_data(financial_data, idx)
            revenue_growth = self.calc_growth(data['매출액'], prev_data['매출액']) if prev_data else None
            op_growth = self.calc_growth(data['영업이익'], prev_data['영업이익']) if prev_data else None
            ni_growth = self.calc_growth(data['순이익'], prev_data['순이익']) if prev_data else None

            # 값 파싱 (원 단위 정수로)
            revenue = self.parse_value(data['매출액'])
            operating_profit = self.parse_value(data['영업이익'])
            net_income = self.parse_value(data['순이익'])

            _, created = Financial.objects.update_or_create(
                stock=info,
                year=year,
                quarter=quarter,
                defaults={
                    'revenue': int(revenue) if revenue else None,
                    'operating_profit': int(operating_profit) if operating_profit else None,
                    'net_income': int(net_income) if net_income else None,
                    'revenue_growth': self._safe_decimal(revenue_growth),
                    'operating_profit_growth': self._safe_decimal(op_growth),
                    'net_income_growth': self._safe_decimal(ni_growth),
                }
            )
            if created:
                saved_count += 1
            else:
                updated_count += 1

        return saved_count, updated_count

    def parse_filename(self, filename):
        """파일명에서 연도와 분기 추출
        예: 2024_1분기보고서_03_포괄손익계산서_20250221.txt -> (2024, '1Q')
        """
        # macOS NFD 정규화 처리
        filename = unicodedata.normalize('NFC', filename)

        # 연도 추출
        year_match = re.match(r'(\d{4})_', filename)
        if not year_match:
            return None, None
        year = int(year_match.group(1))

        # 보고서 종류에서 분기 추출
        for report_type, quarter in REPORT_TO_QUARTER.items():
            if report_type in filename:
                return year, quarter

        return None, None

    def get_income_statement_file(self, jemu_path, comprehensive_filename):
        """포괄손익계산서 파일명에서 손익계산서 파일명 생성"""
        # 03_포괄손익계산서 -> 02_손익계산서
        normalized = unicodedata.normalize('NFC', comprehensive_filename)
        income_filename = normalized.replace('03_포괄손익계산서', '02_손익계산서')

        # 실제 파일 찾기 (NFD 문제 대응)
        for f in os.listdir(jemu_path):
            if unicodedata.normalize('NFC', f) == income_filename:
                return f
        return None

    def load_file(self, filepath):
        """txt 파일 로드 (CP949 인코딩)"""
        df = pd.read_csv(filepath, sep='\t', encoding='cp949')
        return df

    def extract_financial_data(self, jemu_path, filename, stock_code):
        """특정 종목의 재무 데이터 추출"""
        year, quarter = self.parse_filename(filename)
        if not year or not quarter:
            return None

        filepath = os.path.join(jemu_path, filename)

        try:
            df = self.load_file(filepath)
        except Exception:
            return None

        # 컬럼명 (공백 제거)
        columns = [str(c).strip() for c in df.columns.tolist()]
        df.columns = columns

        # 필수 컬럼 확인
        if '종목코드' not in columns or '항목코드' not in columns:
            return None

        config = QUARTER_CONFIG.get(quarter)
        if not config:
            return None

        # 값 컬럼 찾기 (공백 포함된 컬럼명 처리)
        value_column = None
        for col in columns:
            if config['column'] in col:
                value_column = col
                break

        if not value_column:
            return None

        # 종목코드 포맷: [005930]
        target_code = f'[{stock_code}]'

        # 해당 종목 데이터 필터링
        stock_df = df[df['종목코드'] == target_code]

        if stock_df.empty:
            return None

        # 첫 번째 행의 재무제표종류 확인
        first_row_type = stock_df.iloc[0]['재무제표종류']

        # 포괄손익계산서이면 손익계산서 파일에서 데이터 찾기
        if '포괄손익계산서' in str(first_row_type):
            income_filename = self.get_income_statement_file(jemu_path, filename)
            if income_filename:
                income_filepath = os.path.join(jemu_path, income_filename)
                try:
                    income_df = self.load_file(income_filepath)
                    income_columns = [str(c).strip() for c in income_df.columns.tolist()]
                    income_df.columns = income_columns

                    # 값 컬럼 찾기
                    income_value_column = None
                    for col in income_columns:
                        if config['column'] in col:
                            income_value_column = col
                            break

                    if income_value_column:
                        income_stock_df = income_df[income_df['종목코드'] == target_code]
                        if not income_stock_df.empty:
                            stock_df = income_stock_df
                            value_column = income_value_column
                except Exception:
                    pass  # 손익계산서 파일 로드 실패 시 포괄손익계산서 사용

        result = {
            'period': f'{year} {quarter}',
            'year': year,
            'quarter': quarter,
            '매출액': None,
            '영업이익': None,
            '순이익': None,
        }

        for _, row in stock_df.iterrows():
            item_code = str(row['항목코드']).strip() if pd.notna(row['항목코드']) else ''
            value = row[value_column]

            # 항목코드 매칭
            for item_type, target_item_code in ITEM_CODES.items():
                if item_code == target_item_code and result[item_type] is None:
                    result[item_type] = value
                    break

        # 데이터가 하나도 없으면 None 반환
        if result['매출액'] is None and result['영업이익'] is None and result['순이익'] is None:
            return None

        return result

    def parse_value(self, value):
        """문자열 값을 숫자로 변환"""
        if value is None or pd.isna(value):
            return None
        try:
            if isinstance(value, str):
                value = value.replace(',', '')
            return float(value)
        except (ValueError, TypeError):
            return None

    def adjust_4q_data(self, financial_data):
        """4Q 데이터 보정: 연간 누적 - 1Q - 2Q - 3Q"""
        # 연도별로 그룹핑
        by_year = {}
        for data in financial_data:
            year = data['year']
            if year not in by_year:
                by_year[year] = {}
            by_year[year][data['quarter']] = data

        # 4Q 보정
        for year, quarters in by_year.items():
            if '4Q' not in quarters:
                continue

            q4_data = quarters['4Q']

            for item_type in ['매출액', '영업이익', '순이익']:
                q4_value = self.parse_value(q4_data[item_type])
                if q4_value is None:
                    continue

                # 1Q, 2Q, 3Q 값 합산
                sum_q123 = 0
                for q in ['1Q', '2Q', '3Q']:
                    if q in quarters:
                        q_value = self.parse_value(quarters[q][item_type])
                        if q_value is not None:
                            sum_q123 += q_value

                # 4Q = 연간 - (1Q + 2Q + 3Q)
                q4_data[item_type] = q4_value - sum_q123

        return financial_data

    def format_number(self, value):
        """숫자 포맷 (억 단위)"""
        if value is None or pd.isna(value):
            return '-'
        try:
            # 문자열인 경우 쉼표 제거
            if isinstance(value, str):
                value = value.replace(',', '')
            num = float(value)
            # 억 단위로 변환 (원 -> 억)
            억 = num / 100000000
            if abs(억) >= 1:
                return f'{억:,.0f}억'
            else:
                return f'{num:,.0f}'
        except (ValueError, TypeError):
            return str(value)

    def format_ratio(self, value):
        """비율 포맷 (%)"""
        if value is None:
            return '-'
        return f'{value:.1f}%'

    def format_growth(self, value):
        """증가율 포맷 (%)"""
        if value is None:
            return '-'
        sign = '+' if value > 0 else ''
        return f'{sign}{value:.1f}%'

    def calc_ratio(self, numerator, denominator):
        """비율 계산 (분자/분모 * 100)"""
        num = self.parse_value(numerator)
        den = self.parse_value(denominator)
        if num is None or den is None or den == 0:
            return None
        return (num / den) * 100

    def calc_growth(self, current, previous):
        """증가율 계산 ((현재-이전)/|이전| * 100)"""
        curr = self.parse_value(current)
        prev = self.parse_value(previous)
        if curr is None or prev is None or prev == 0:
            return None
        result = ((curr - prev) / abs(prev)) * 100
        # inf, nan, 또는 너무 큰 값 체크
        if math.isnan(result) or math.isinf(result) or abs(result) > 99999999:
            return None
        return result

    def _safe_decimal(self, value):
        """안전한 Decimal 변환 (실패 시 None 반환)"""
        if value is None:
            return None
        try:
            return Decimal(str(round(value, 2)))
        except (InvalidOperation, ValueError, OverflowError):
            return None

    def get_annual_data(self, financial_data):
        """4Q 데이터만 추출 (연간 누적 값 그대로 사용)"""
        annual_data = []
        for data in financial_data:
            if data['quarter'] == '4Q':
                # period를 연도만 표시하도록 변경
                annual_entry = data.copy()
                annual_entry['period'] = str(data['year'])
                annual_data.append(annual_entry)
        return annual_data

    def get_previous_data(self, financial_data, current_idx):
        """이전 데이터 찾기 (전분기 또는 전년)"""
        if current_idx <= 0:
            return None
        return financial_data[current_idx - 1]

    def print_financial_table(self, stock_code, financial_data, is_annual=False):
        """재무 데이터 표 출력"""
        if not financial_data:
            self.stdout.write(self.style.ERROR(f'종목코드 {stock_code}의 데이터가 없습니다.'))
            return

        data_type = '연간' if is_annual else '분기'
        self.stdout.write(f'\n종목코드: {stock_code} ({data_type})')
        self.stdout.write('=' * 95)
        self.stdout.write(
            f'{"기간":<10} {"매출액":>12} {"증가율":>8} '
            f'{"영업이익":>12} {"증가율":>8} '
            f'{"순이익":>12} {"증가율":>8}'
        )
        self.stdout.write('-' * 95)

        for idx, data in enumerate(financial_data):
            period = data['period']
            prev_data = self.get_previous_data(financial_data, idx)

            # 매출액
            매출액 = self.format_number(data['매출액'])
            매출액_증가율 = self.format_growth(
                self.calc_growth(data['매출액'], prev_data['매출액']) if prev_data else None
            )

            # 영업이익
            영업이익 = self.format_number(data['영업이익'])
            영업이익_증가율 = self.format_growth(
                self.calc_growth(data['영업이익'], prev_data['영업이익']) if prev_data else None
            )

            # 순이익
            순이익 = self.format_number(data['순이익'])
            순이익_증가율 = self.format_growth(
                self.calc_growth(data['순이익'], prev_data['순이익']) if prev_data else None
            )

            self.stdout.write(
                f'{period:<10} {매출액:>12} {매출액_증가율:>8} '
                f'{영업이익:>12} {영업이익_증가율:>8} '
                f'{순이익:>12} {순이익_증가율:>8}'
            )

        self.stdout.write('=' * 95)

    def save_to_db(self, stock_code, financial_data, is_annual=False):
        """재무 데이터를 DB에 저장"""
        # Info 조회
        try:
            info = Info.objects.get(code=stock_code)
        except Info.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'종목코드 {stock_code}가 Info에 없습니다.'))
            return

        saved_count = 0
        updated_count = 0

        for idx, data in enumerate(financial_data):
            year = data['year']
            quarter = None if is_annual else data['quarter']

            # 증가율 계산
            prev_data = self.get_previous_data(financial_data, idx)
            revenue_growth = self.calc_growth(data['매출액'], prev_data['매출액']) if prev_data else None
            op_growth = self.calc_growth(data['영업이익'], prev_data['영업이익']) if prev_data else None
            ni_growth = self.calc_growth(data['순이익'], prev_data['순이익']) if prev_data else None

            # 값 파싱 (원 단위 정수로)
            revenue = self.parse_value(data['매출액'])
            operating_profit = self.parse_value(data['영업이익'])
            net_income = self.parse_value(data['순이익'])

            # Financial 조회 또는 생성
            financial, created = Financial.objects.update_or_create(
                stock=info,
                year=year,
                quarter=quarter,
                defaults={
                    'revenue': int(revenue) if revenue else None,
                    'operating_profit': int(operating_profit) if operating_profit else None,
                    'net_income': int(net_income) if net_income else None,
                    'revenue_growth': self._safe_decimal(revenue_growth),
                    'operating_profit_growth': self._safe_decimal(op_growth),
                    'net_income_growth': self._safe_decimal(ni_growth),
                }
            )

            if created:
                saved_count += 1
            else:
                updated_count += 1

        data_type = '연간' if is_annual else '분기'
        self.stdout.write(self.style.SUCCESS(
            f'\n{info.name}({stock_code}) {data_type} 데이터 저장 완료: 신규 {saved_count}건, 업데이트 {updated_count}건'
        ))
