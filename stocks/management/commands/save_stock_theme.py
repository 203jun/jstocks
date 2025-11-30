import requests
import json
import time
from django.core.management.base import BaseCommand
from stocks.utils import get_valid_token
from stocks.models import Info, Theme
from stocks.logger import StockLogger


class Command(BaseCommand):
    help = '''
    종목-테마 매핑 데이터 저장 (테마구성종목요청 - ka90002)

    ※ 동작 방식:
    1. Theme 테이블에서 모든 고유한 테마그룹코드 가져오기
    2. 각 테마그룹코드로 ka90002 API 호출
    3. Info.themes에 매핑 (ManyToMany 관계 연결)

    ※ 실행 순서:
    1. python manage.py save_theme --mode all  (먼저 실행)
    2. python manage.py save_stock_theme  (이 명령어)
    '''

    def add_arguments(self, parser):
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        # 로거 초기화
        self.log = StockLogger(self.stdout, self.style, options, 'save_stock_theme')

        # 1. 토큰 가져오기
        token = get_valid_token()

        if not token:
            self.log.error('토큰이 없습니다. python manage.py get_token을 먼저 실행하세요.')
            return

        # 2. Theme 테이블 확인
        theme_count = Theme.objects.count()
        if theme_count == 0:
            self.log.error('Theme 테이블이 비어있습니다!')
            self.log.debug('먼저 python manage.py save_theme --mode all 실행')
            return

        self.log.debug(f'Theme 데이터 확인 완료 ({theme_count:,}개 레코드)')

        # 3. 고유한 테마그룹코드 가져오기
        theme_codes = Theme.objects.values_list('code', flat=True).distinct().order_by('code')
        theme_codes_list = list(theme_codes)

        self.log.info(f'총 {len(theme_codes_list)}개 테마그룹코드 발견')
        self.log.separator()

        # 4. 각 테마그룹코드에 대해 API 호출 및 매핑
        self.process_all_themes(token, theme_codes_list)

    def process_all_themes(self, token, theme_codes_list):
        """모든 테마에 대해 API 호출하고 종목-테마 매핑"""
        total_count = len(theme_codes_list)
        success_count = 0
        fail_count = 0
        total_mappings = 0

        for idx, theme_code in enumerate(theme_codes_list, start=1):
            self.log.debug(f'[{idx}/{total_count}] 테마 {theme_code} 처리 중...')

            # API 호출
            params = {
                'date_tp': '1',
                'thema_grp_cd': theme_code,
                'stex_tp': '1',
            }

            response_data = self.call_api(token, params)

            if not response_data:
                self.log.debug(f'  → API 호출 실패')
                fail_count += 1
                continue

            # 종목 리스트 추출
            data_key = self.find_data_key(response_data)
            if not data_key or not response_data[data_key]:
                self.log.debug(f'  → 구성 종목 데이터 없음')
                fail_count += 1
                continue

            stock_list = response_data[data_key]
            self.log.debug(f'  → {len(stock_list)}개 종목 발견')

            # Theme 객체 가져오기 (최신 날짜)
            theme = Theme.objects.filter(code=theme_code).order_by('-date').first()

            if not theme:
                self.log.debug(f'  → Theme 객체 없음')
                fail_count += 1
                continue

            # 종목-테마 매핑
            mapped_count = self.map_stocks_to_theme(stock_list, theme)
            total_mappings += mapped_count
            success_count += 1

            self.log.debug(f'  → {mapped_count}개 종목 매핑 완료')

            # API 호출 제한 방지 (0.5초 대기)
            time.sleep(0.5)

        # 최종 결과
        self.log.info(f'처리 완료! 성공: {success_count}개 테마, 실패: {fail_count}개 테마, 총 매핑: {total_mappings}개', success=True)

    def map_stocks_to_theme(self, stock_list, theme):
        """종목 리스트와 테마를 매핑"""
        mapped_count = 0

        for stock_data in stock_list:
            stock_code = stock_data.get('stk_cd')

            if not stock_code:
                continue

            try:
                info = Info.objects.get(code=stock_code)
                info.themes.add(theme)
                mapped_count += 1

            except Info.DoesNotExist:
                pass
            except Exception as e:
                self.log.error(f'매핑 실패 ({stock_code}): {str(e)}')

        return mapped_count

    def find_data_key(self, response_data):
        """응답에서 데이터 배열 키 찾기"""
        for key in ['thema_comp_stk', 'data', 'result', 'output']:
            if key in response_data and isinstance(response_data[key], list):
                return key
        return None

    def call_api(self, token, data, cont_yn='N', next_key=''):
        """테마구성종목요청 API 호출"""
        host = 'https://api.kiwoom.com'
        endpoint = '/api/dostk/thme'
        url = host + endpoint

        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'authorization': f'Bearer {token}',
            'cont-yn': cont_yn,
            'next-key': next_key,
            'api-id': 'ka90002',
        }

        try:
            response = requests.post(url, headers=headers, json=data)

            if response.status_code != 200:
                self.log.error(f'API 호출 실패: {response.status_code}')
                return None

            response_data = response.json()

            return response_data

        except Exception as e:
            self.log.error(f'API 호출 실패: {str(e)}')
            return None
