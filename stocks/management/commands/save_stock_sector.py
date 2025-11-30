import requests
import json
import time
from django.core.management.base import BaseCommand
from stocks.utils import get_valid_token
from stocks.models import Info, Sector


class Command(BaseCommand):
    help = '''
    종목-업종 매핑 데이터 저장 (업종별주가요청 - ka20002)

    ※ 동작 방식:
    1. Sector 테이블에서 모든 고유한 (업종코드, 시장) 조합 가져오기
    2. 각 업종별로 ka20002 API 호출 (업종 개수만큼 반복)
    3. API 응답에서 해당 업종에 속한 종목 리스트(stk_cd) 추출
    4. Info.sectors에 매핑 (ManyToMany 관계 연결)

    ※ 전제조건:
    - Sector 테이블에 업종 데이터가 먼저 저장되어 있어야 함
    - Info 테이블에 종목 정보가 있어야 함

    ※ 실행 순서:
    1. python manage.py save_sector --mode all  (먼저 실행)
    2. python manage.py save_stock_sector  (이 명령어)
    '''

    def handle(self, *args, **options):
        # 1. 토큰 가져오기
        token = get_valid_token()

        if not token:
            self.stdout.write(self.style.ERROR('토큰이 없습니다. python manage.py get_token을 먼저 실행하세요.'))
            return

        # 2. Sector 테이블 확인
        sector_count = Sector.objects.count()
        if sector_count == 0:
            self.stdout.write(self.style.ERROR('\n[오류] Sector 테이블이 비어있습니다!'))
            self.stdout.write(self.style.WARNING('먼저 다음 명령어를 실행하세요:'))
            self.stdout.write('  python manage.py save_sector --mode all\n')
            return

        self.stdout.write(self.style.SUCCESS(f'✓ Sector 데이터 확인 완료 ({sector_count:,}개 레코드)'))

        # 3. 고유한 (업종코드, 시장) 조합 가져오기
        # 최신 날짜 기준으로 업종 정보 가져오기
        sectors = Sector.objects.values('code', 'market').distinct().order_by('code', 'market')
        sectors_list = list(sectors)

        self.stdout.write(f'\n총 {len(sectors_list)}개 업종 발견')
        self.stdout.write('=' * 70)

        # 4. 각 업종에 대해 API 호출 및 매핑
        self.process_all_sectors(token, sectors_list)

    def process_all_sectors(self, token, sectors_list):
        """
        모든 업종에 대해 API 호출하고 종목-업종 매핑

        Args:
            token: API 인증 토큰
            sectors_list: [{'code': '001', 'market': 'KOSPI'}, ...] 형태의 리스트
        """
        total_count = len(sectors_list)
        success_count = 0
        fail_count = 0
        total_mappings = 0

        for idx, sector_info in enumerate(sectors_list, start=1):
            sector_code = sector_info['code']
            market = sector_info['market']

            self.stdout.write(f'\n[{idx}/{total_count}] 업종 {sector_code} ({market}) 처리 중...')

            # 시장 구분 변환 (KOSPI→0, KOSDAQ→1)
            mrkt_tp = '0' if market == 'KOSPI' else '1'

            # API 호출
            params = {
                'mrkt_tp': mrkt_tp,
                'inds_cd': sector_code,
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

            # Sector 객체 가져오기 (최신 날짜)
            sector = Sector.objects.filter(
                code=sector_code,
                market=market
            ).order_by('-date').first()

            if not sector:
                self.stdout.write(self.style.WARNING(f'  → Sector 객체 없음'))
                fail_count += 1
                continue

            # 종목-업종 매핑
            mapped_count = self.map_stocks_to_sector(stock_list, sector)
            total_mappings += mapped_count
            success_count += 1

            self.stdout.write(self.style.SUCCESS(f'  → {mapped_count}개 종목 매핑 완료'))

            # API 호출 제한 방지 (0.5초 대기)
            time.sleep(0.5)

        # 최종 결과
        self.stdout.write('\n' + '=' * 70)
        self.stdout.write(self.style.SUCCESS(f'\n✓ 처리 완료!'))
        self.stdout.write(f'  - 성공: {success_count}개 업종')
        self.stdout.write(f'  - 실패: {fail_count}개 업종')
        self.stdout.write(f'  - 총 매핑: {total_mappings}개 종목-업종 관계')

    def map_stocks_to_sector(self, stock_list, sector):
        """
        종목 리스트와 업종을 매핑

        Args:
            stock_list: API 응답의 종목 리스트
            sector: Sector 객체

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

                # Sector와 연결 (이미 연결되어 있으면 중복 추가 안 됨)
                info.sectors.add(sector)
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
        for key in ['inds_stkpc', 'data', 'result', 'output']:
            if key in response_data and isinstance(response_data[key], list):
                return key
        return None

    def call_api(self, token, data):
        """업종별주가요청 API 호출"""
        # 1. 요청할 API URL
        host = 'https://api.kiwoom.com'  # 실전투자
        # host = 'https://mockapi.kiwoom.com'  # 모의투자
        endpoint = '/api/dostk/sect'
        url = host + endpoint

        # 2. header 데이터
        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'authorization': f'Bearer {token}',
            'api-id': 'ka20002',
        }

        try:
            # 3. http POST 요청
            response = requests.post(url, headers=headers, json=data)

            # 응답 상태 코드 확인
            if response.status_code != 200:
                return None

            # 응답 데이터 파싱
            response_data = response.json()

            return response_data

        except Exception:
            return None
