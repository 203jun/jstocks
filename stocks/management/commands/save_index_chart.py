import re
import requests
from datetime import datetime, timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand
from stocks.models import IndexChart
from stocks.logger import StockLogger


class Command(BaseCommand):
    help = '지수(KOSPI/KOSDAQ) 일봉 차트 데이터 저장 (네이버 금융)'

    # 지원하는 지수 코드
    INDEX_CODES = ['KOSPI', 'KOSDAQ']

    def add_arguments(self, parser):
        parser.add_argument(
            '--code',
            type=str,
            default='all',
            help='지수코드: KOSPI, KOSDAQ, all (기본값: all)'
        )
        parser.add_argument(
            '--mode',
            type=str,
            default='last',
            choices=['all', 'last'],
            help='all: 2024.1.1부터, last: 마지막 저장일부터 (기본값: last)'
        )
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        self.log = StockLogger(self.stdout, self.style, options, 'save_index_chart')

        code = options['code'].upper()
        mode = options['mode']

        if code == 'ALL':
            codes = self.INDEX_CODES
        elif code in self.INDEX_CODES:
            codes = [code]
        else:
            self.log.error(f'지원하지 않는 지수코드: {code}')
            self.log.info(f'지원 코드: {", ".join(self.INDEX_CODES)}')
            return

        self.log.info(f'지수 차트 저장 시작 (mode={mode})')

        for index_code in codes:
            self.process_index(index_code, mode)

        self.log.separator()
        self.log.info('지수 차트 저장 완료', success=True)

    def process_index(self, code, mode):
        """지수 데이터 처리"""
        self.log.separator()
        self.log.info(f'[{code}] 처리 시작')

        # 시작일 결정
        if mode == 'all':
            start_date = datetime(2024, 1, 1).date()
        else:
            # 마지막 저장일 조회
            last_record = IndexChart.objects.filter(code=code).order_by('-date').first()
            if last_record:
                start_date = last_record.date + timedelta(days=1)
            else:
                start_date = datetime(2024, 1, 1).date()

        end_date = datetime.now().date()

        if start_date > end_date:
            self.log.info(f'[{code}] 이미 최신 데이터')
            return

        self.log.info(f'[{code}] 기간: {start_date} ~ {end_date}')

        # 데이터 가져오기
        data = self.fetch_data(code, start_date, end_date)

        if not data:
            self.log.info(f'[{code}] 데이터 없음')
            return

        # 저장
        created_count = 0
        updated_count = 0

        for row in data:
            try:
                date_str = row[0]
                date = datetime.strptime(date_str, '%Y%m%d').date()

                obj, created = IndexChart.objects.update_or_create(
                    code=code,
                    date=date,
                    defaults={
                        'opening_price': Decimal(str(row[1])),
                        'high_price': Decimal(str(row[2])),
                        'low_price': Decimal(str(row[3])),
                        'closing_price': Decimal(str(row[4])),
                        'trading_volume': int(row[5]),
                    }
                )

                if created:
                    created_count += 1
                else:
                    updated_count += 1

            except Exception as e:
                self.log.error(f'[{code}] 저장 실패: {row} - {e}')

        self.log.info(f'[{code}] 신규 {created_count}개, 업데이트 {updated_count}개', success=True)

    def fetch_data(self, code, start_date, end_date):
        """네이버 금융 API에서 데이터 가져오기"""
        url = 'https://fchart.stock.naver.com/siseJson.nhn'
        params = {
            'symbol': code,
            'requestType': 1,
            'startTime': start_date.strftime('%Y%m%d'),
            'endTime': end_date.strftime('%Y%m%d'),
            'timeframe': 'day',
        }

        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()

            # 응답 파싱 (JavaScript 배열 형식)
            text = response.text.strip()

            # 헤더 행 제거하고 데이터만 추출
            # [['날짜', '시가', ...], ["20241201", 2479.02, ...], ...]
            rows = []
            for line in text.split('\n'):
                line = line.strip()
                if not line:
                    continue
                # 날짜 데이터 행만 추출 (["20241201", ...] 형식)
                match = re.search(r'\["(\d{8})",\s*([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*(\d+)', line)
                if match:
                    rows.append([
                        match.group(1),  # 날짜
                        float(match.group(2)),  # 시가
                        float(match.group(3)),  # 고가
                        float(match.group(4)),  # 저가
                        float(match.group(5)),  # 종가
                        int(match.group(6)),  # 거래량
                    ])

            return rows

        except Exception as e:
            self.log.error(f'API 호출 실패: {e}')
            return []
