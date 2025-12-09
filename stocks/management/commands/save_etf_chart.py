import requests
import json
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from stocks.models import InfoETF, DailyChartETF, WeeklyChartETF, MonthlyChartETF
from stocks.logger import StockLogger


class Command(BaseCommand):
    help = '''
ETF 차트 조회 및 저장 (네이버 금융 API)

일봉, 주봉, 월봉을 한번에 저장합니다.

옵션:
  --code      (선택) ETF 코드 또는 "all" (기본값: all)
  --mode      (선택) all / last (기본값: last)
  --clear     (선택) 전체 데이터 삭제
  --log-level (선택) debug / info / warning / error (기본값: info)

모드:
  all:  일봉 2년, 주봉 4년, 월봉 6년
  last: 일봉 30일, 주봉 12주, 월봉 12개월

예시:
  python manage.py save_etf_chart
  python manage.py save_etf_chart --code 305720 --mode all
  python manage.py save_etf_chart --mode all
  python manage.py save_etf_chart --clear
'''

    def add_arguments(self, parser):
        parser.add_argument(
            '--code',
            type=str,
            default='all',
            help='ETF 코드 또는 "all" (기본값: all)'
        )
        parser.add_argument(
            '--mode',
            type=str,
            choices=['all', 'last'],
            default='last',
            help='조회 모드: all(전체), last(최신만)'
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
            d1, _ = DailyChartETF.objects.all().delete()
            d2, _ = WeeklyChartETF.objects.all().delete()
            d3, _ = MonthlyChartETF.objects.all().delete()
            self.stdout.write(self.style.SUCCESS(
                f'ETF 차트 데이터 삭제 완료 (일봉: {d1}, 주봉: {d2}, 월봉: {d3})'
            ))
            return

        # 로거 초기화
        self.log = StockLogger(self.stdout, self.style, options, 'save_etf_chart')

        # 파라미터 설정
        code = options['code']
        mode = options['mode']
        process_all = code.lower() == 'all'

        # 처리
        if process_all:
            self.process_all_etfs(mode)
        else:
            self.process_single_etf(code, mode)

    def process_single_etf(self, etf_code, mode):
        """단일 ETF 처리"""
        try:
            etf = InfoETF.objects.get(code=etf_code)
            etf_name = etf.name
        except InfoETF.DoesNotExist:
            self.log.error(f'ETF 정보 없음: {etf_code}')
            return

        self.log.info(f'ETF: {etf_name}({etf_code}) | 모드: {mode}')
        self.log.separator()

        result = self.fetch_and_save(etf, mode)
        self.log.info(f'결과: {result}', success=True)

    def process_all_etfs(self, mode):
        """전체 관심 ETF 처리"""
        import time

        etfs = InfoETF.objects.filter(is_active=True)
        total = etfs.count()

        if total == 0:
            self.log.warning('관심 ETF가 없습니다.')
            return

        self.log.info(f'ETF 차트 저장 시작 (모드: {mode}, 대상: {total}개)')

        success_count = 0
        error_list = []

        for idx, etf in enumerate(etfs, 1):
            try:
                result = self.fetch_and_save(etf, mode, silent=True)
                self.log.info(f'[{idx}/{total}] {etf.code} {etf.name}: {result}')
                success_count += 1
                time.sleep(0.5)  # API 요청 간격
            except Exception as e:
                self.log.error(f'[{idx}/{total}] {etf.code} {etf.name}: 실패 - {str(e)}')
                error_list.append((etf.code, etf.name, str(e)))

        # 최종 리포트
        self.log.separator()
        if error_list:
            self.log.info(f'완료 | 성공: {success_count}개, 오류: {len(error_list)}개', success=True)
            self.log.info('')
            self.log.info('[오류 목록]')
            for code, name, err in error_list:
                self.log.error(f'  {code} {name}: {err}')
        else:
            self.log.info(f'완료 | 성공: {success_count}개', success=True)

    def fetch_and_save(self, etf, mode, silent=False):
        """ETF 차트 데이터 조회 및 저장 (일봉, 주봉, 월봉)"""
        # 일봉
        daily_new, daily_upd = self.fetch_chart(etf, 'day', mode, silent)

        # 주봉
        weekly_new, weekly_upd = self.fetch_chart(etf, 'week', mode, silent)

        # 월봉
        monthly_new, monthly_upd = self.fetch_chart(etf, 'month', mode, silent)

        def fmt(new, upd):
            if new > 0 and upd > 0:
                return f'신규 {new}, 업데이트 {upd}'
            elif new > 0:
                return f'신규 {new}'
            elif upd > 0:
                return f'업데이트 {upd}'
            return '0'

        return f'일봉({fmt(daily_new, daily_upd)}), 주봉({fmt(weekly_new, weekly_upd)}), 월봉({fmt(monthly_new, monthly_upd)})'

    def fetch_chart(self, etf, timeframe, mode, silent=False):
        """
        특정 타임프레임 차트 데이터 조회 및 저장

        Args:
            etf: InfoETF 객체
            timeframe: 'day', 'week', 'month'
            mode: 'all' or 'last'
            silent: 로그 출력 여부
        """
        # 기간 계산
        today = datetime.now()
        if mode == 'all':
            if timeframe == 'day':
                start_date = today - timedelta(days=730)  # 2년
            elif timeframe == 'week':
                start_date = today - timedelta(days=1460)  # 4년
            else:  # month
                start_date = today - timedelta(days=2190)  # 6년
        else:  # last
            if timeframe == 'day':
                start_date = today - timedelta(days=30)
            elif timeframe == 'week':
                start_date = today - timedelta(weeks=12)
            else:  # month
                start_date = today - timedelta(days=365)

        start_str = start_date.strftime('%Y%m%d')
        end_str = today.strftime('%Y%m%d')

        # 네이버 API 호출
        url = 'https://api.finance.naver.com/siseJson.naver'
        params = {
            'symbol': etf.code,
            'requestType': '1',
            'startTime': start_str,
            'endTime': end_str,
            'timeframe': timeframe,
        }
        headers = {'User-Agent': 'Mozilla/5.0'}

        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
        except Exception as e:
            if not silent:
                self.log.error(f'API 호출 실패: {str(e)}')
            return (0, 0)

        # JSON 파싱 (네이버 응답은 전처리 필요)
        try:
            text = response.text.strip()
            # 단일 따옴표 -> 이중 따옴표
            text = text.replace("'", '"')
            # 탭, 개행 정리
            text = text.replace('\n', '').replace('\t', '')
            # 마지막 쉼표 제거 (JSON 오류 방지)
            text = text.replace(',]', ']')
            data = json.loads(text)
        except json.JSONDecodeError as e:
            if not silent:
                self.log.error(f'JSON 파싱 실패: {str(e)}')
            return (0, 0)

        if not data or len(data) < 2:
            return (0, 0)

        # 첫 번째 행은 헤더, 나머지가 데이터
        # ['날짜', '시가', '고가', '저가', '종가', '거래량', '외국인소진율']
        chart_data = data[1:]  # 헤더 제외

        # 모델 선택
        if timeframe == 'day':
            ChartModel = DailyChartETF
        elif timeframe == 'week':
            ChartModel = WeeklyChartETF
        else:
            ChartModel = MonthlyChartETF

        # DB 저장
        created_count = 0
        updated_count = 0

        for row in chart_data:
            if len(row) < 6:
                continue

            try:
                date_str = str(row[0])
                date = datetime.strptime(date_str, '%Y%m%d').date()

                chart, created = ChartModel.objects.update_or_create(
                    etf=etf,
                    date=date,
                    defaults={
                        'opening_price': int(row[1]),
                        'high_price': int(row[2]),
                        'low_price': int(row[3]),
                        'closing_price': int(row[4]),
                        'trading_volume': int(row[5]),
                    }
                )

                if created:
                    created_count += 1
                else:
                    updated_count += 1

            except Exception as e:
                if not silent:
                    self.log.debug(f'저장 실패 ({row}): {str(e)}')

        return (created_count, updated_count)
