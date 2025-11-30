import requests
import json
import time
from django.core.management.base import BaseCommand
from stocks.utils import get_valid_token
from stocks.models import Info, Theme


class Command(BaseCommand):
    help = '''
    종목-테마 매핑 데이터 저장 (테마구성종목요청 - ka90002)

    ※ 동작 방식:
    1. Theme 테이블에서 모든 고유한 테마그룹코드 가져오기
    2. 각 테마그룹코드로 ka90002 API 호출 (테마 개수만큼 반복)
    3. API 응답에서 해당 테마에 속한 종목 리스트(stk_cd) 추출
    4. Info.themes에 매핑 (ManyToMany 관계 연결)

    ※ 전제조건:
    - Theme 테이블에 테마 데이터가 먼저 저장되어 있어야 함
    - Info 테이블에 종목 정보가 있어야 함

    ※ 실행 순서:
    1. python manage.py save_theme --mode all  (먼저 실행)
    2. python manage.py save_stock_theme  (이 명령어)
    '''

    def handle(self, *args, **options):
        # 1. 토큰 가져오기
        token = get_valid_token()

        if not token:
            self.stdout.write(self.style.ERROR('토큰이 없습니다. python manage.py get_token을 먼저 실행하세요.'))
            return

        # 2. Theme 테이블 확인
        theme_count = Theme.objects.count()
        if theme_count == 0:
            self.stdout.write(self.style.ERROR('\n[오류] Theme 테이블이 비어있습니다!'))
            self.stdout.write(self.style.WARNING('먼저 다음 명령어를 실행하세요:'))
            self.stdout.write('  python manage.py save_theme --mode all\n')
            return

        self.stdout.write(self.style.SUCCESS(f'✓ Theme 데이터 확인 완료 ({theme_count:,}개 레코드)'))

        # 3. 고유한 테마그룹코드 가져오기
        theme_codes = Theme.objects.values_list('code', flat=True).distinct().order_by('code')
        theme_codes_list = list(theme_codes)

        self.stdout.write(f'\n총 {len(theme_codes_list)}개 테마그룹코드 발견')
        self.stdout.write('=' * 70)

        # 4. 각 테마그룹코드에 대해 API 호출 및 매핑
        self.process_all_themes(token, theme_codes_list)

    def process_all_themes(self, token, theme_codes_list):
        """
        모든 테마에 대해 API 호출하고 종목-테마 매핑

        Args:
            token: API 인증 토큰
            theme_codes_list: 테마그룹코드 리스트
        """
        total_count = len(theme_codes_list)
        success_count = 0
        fail_count = 0
        total_mappings = 0

        for idx, theme_code in enumerate(theme_codes_list, start=1):
            self.stdout.write(f'\n[{idx}/{total_count}] 테마 {theme_code} 처리 중...')

            # API 호출
            params = {
                'date_tp': '1',  # 1일 기준
                'thema_grp_cd': theme_code,
                'stex_tp': '1',  # KRX
            }

            response_data = self.call_api(token, params)

            if not response_data:
                self.stdout.write(self.style.WARNING(f'  → API 호출 실패'))
                fail_count += 1
                continue

            # 종목 리스트 추출
            data_key = self.find_data_key(response_data)
            if not data_key or not response_data[data_key]:
                self.stdout.write(self.style.WARNING(f'  → 구성 종목 데이터 없음'))
                fail_count += 1
                continue

            stock_list = response_data[data_key]
            self.stdout.write(f'  → {len(stock_list)}개 종목 발견')

            # Theme 객체 가져오기 (최신 날짜)
            theme = Theme.objects.filter(code=theme_code).order_by('-date').first()

            if not theme:
                self.stdout.write(self.style.WARNING(f'  → Theme 객체 없음'))
                fail_count += 1
                continue

            # 종목-테마 매핑
            mapped_count = self.map_stocks_to_theme(stock_list, theme)
            total_mappings += mapped_count
            success_count += 1

            self.stdout.write(self.style.SUCCESS(f'  → {mapped_count}개 종목 매핑 완료'))

            # API 호출 제한 방지 (0.5초 대기)
            time.sleep(0.5)

        # 최종 결과
        self.stdout.write('\n' + '=' * 70)
        self.stdout.write(self.style.SUCCESS(f'\n✓ 처리 완료!'))
        self.stdout.write(f'  - 성공: {success_count}개 테마')
        self.stdout.write(f'  - 실패: {fail_count}개 테마')
        self.stdout.write(f'  - 총 매핑: {total_mappings}개 종목-테마 관계')

    def map_stocks_to_theme(self, stock_list, theme):
        """
        종목 리스트와 테마를 매핑

        Args:
            stock_list: API 응답의 종목 리스트
            theme: Theme 객체

        Returns:
            int: 매핑된 종목 수
        """
        mapped_count = 0

        for stock_data in stock_list:
            stock_code = stock_data.get('stk_cd')

            if not stock_code:
                continue

            try:
                # Info 객체 가져오기
                info = Info.objects.get(code=stock_code)

                # Theme과 연결 (이미 연결되어 있으면 중복 추가 안 됨)
                info.themes.add(theme)
                mapped_count += 1

            except Info.DoesNotExist:
                # Info가 없는 종목은 스킵 (로그 출력 안 함)
                pass
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'    매핑 실패 ({stock_code}): {str(e)}')
                )

        return mapped_count

    def find_data_key(self, response_data):
        """응답에서 데이터 배열 키 찾기"""
        for key in ['thema_comp_stk', 'data', 'result', 'output']:
            if key in response_data and isinstance(response_data[key], list):
                return key
        return None

    def call_api(self, token, data, cont_yn='N', next_key=''):
        """테마구성종목요청 API 호출"""
        # 1. 요청할 API URL
        host = 'https://api.kiwoom.com'  # 실전투자
        # host = 'https://mockapi.kiwoom.com'  # 모의투자
        endpoint = '/api/dostk/thme'
        url = host + endpoint

        # 2. header 데이터
        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'authorization': f'Bearer {token}',
            'cont-yn': cont_yn,
            'next-key': next_key,
            'api-id': 'ka90002',
        }

        try:
            # 3. http POST 요청
            response = requests.post(url, headers=headers, json=data)

            # 응답 상태 코드 확인
            if response.status_code != 200:
                self.stdout.write(self.style.ERROR(f'API 호출 실패: {response.status_code}'))
                return None

            # 응답 데이터 파싱
            response_data = response.json()

            return response_data

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'API 호출 실패: {str(e)}'))
            return None
