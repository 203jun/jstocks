import re
import requests
from datetime import datetime, timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from stocks.models import IndexChart
from stocks.logger import StockLogger


class FetchFailed(Exception):
    """못 받았다. '받을 것이 없다' 와 다른 일이다."""


class Command(BaseCommand):
    help = '''
지수(KOSPI/KOSDAQ) 일봉 차트 데이터 저장 (네이버 금융)

옵션:
  --market    (선택) KOSPI / KOSDAQ / all (기본값: all)
  --mode      (선택) all (2024.1.1부터) / last (마지막 저장일부터, 기본값)
  --clear     (선택) 전체 데이터 삭제
  --log-level (선택) debug / info / warning / error (기본값: info)

예시:
  python manage.py save_index_chart
  python manage.py save_index_chart --market KOSPI --mode all
  python manage.py save_index_chart --clear
'''

    # 지원하는 지수 코드
    INDEX_CODES = ['KOSPI', 'KOSDAQ']

    def add_arguments(self, parser):
        parser.add_argument(
            '--market',
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
        parser.add_argument(
            '--clear',
            action='store_true',
            help='전체 데이터 삭제'
        )
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        # --clear 옵션 처리
        if options.get('clear'):
            deleted_count, _ = IndexChart.objects.all().delete()
            self.stdout.write(self.style.SUCCESS(f'IndexChart 데이터 {deleted_count}건 삭제 완료'))
            return

        self.log = StockLogger(self.stdout, self.style, options, 'save_index_chart')

        market = options['market'].upper()
        mode = options['mode']

        if market == 'ALL':
            codes = self.INDEX_CODES
        elif market in self.INDEX_CODES:
            codes = [market]
        else:
            self.log.error(f'지원하지 않는 지수코드: {market}')
            self.log.info(f'지원 코드: {", ".join(self.INDEX_CODES)}')
            return

        self.log.info(f'지수 차트 저장 시작 (모드: {mode}, 대상: {", ".join(codes)})')

        total_created = 0
        total_updated = 0
        errors = []

        for index_code in codes:
            try:
                created, updated = self.process_index(index_code, mode)
            except FetchFailed as e:
                self.log.error(f'[{index_code}] 조회 실패: {e}')
                errors.append(f'{index_code}: {e}')
                continue
            total_created += created
            total_updated += updated

        self.log.separator()
        # '오류: N개' 는 배치가 출력에서 집어내 텔레그램에 싣는 공통 관례다
        # (batch_lib.sh).
        if errors:
            self.log.info(f'완료 | 신규: {total_created}개, 업데이트: {total_updated}개, '
                          f'오류: {len(errors)}개', success=True)
            self.log.info('')
            self.log.info('[오류 목록]')
            for e in errors:
                self.log.error(f'  {e}')
        else:
            self.log.info(f'완료 | 신규: {total_created}개, 업데이트: {total_updated}개',
                          success=True)

        # 하나도 못 받았으면 비정상 종료로 끝낸다. 로그만 찍고 0 으로 끝나면
        # 배치가 '완료' 를 보낸다 — ETF 정보가 그렇게 넉 달을 멈춰 있었다.
        if errors and len(errors) == len(codes):
            raise CommandError(
                f'지수 차트를 하나도 받지 못했습니다 ({", ".join(codes)}).')

    def process_index(self, code, mode):
        """지수 데이터 처리, (created, updated) 반환"""
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
            return 0, 0

        self.log.debug(f'[{code}] 기간: {start_date} ~ {end_date}')

        # 데이터 가져오기 (실패하면 FetchFailed 가 올라간다)
        data = self.fetch_data(code, start_date, end_date)

        if not data:
            self.log.info(f'[{code}] 데이터 없음')
            return 0, 0

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

        self.log.info(f'[{code}] 신규 {created_count}개, 업데이트 {updated_count}개')
        return created_count, updated_count

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
            # 빈 리스트로 돌려주면 '오늘은 받을 것이 없었다' 와 구분되지 않는다.
            # 그래서 조용히 넘어가고 배치는 '완료' 를 보낸다.
            raise FetchFailed(str(e)) from e
