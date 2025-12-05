import requests
import json
import time
from django.core.management.base import BaseCommand
from stocks.utils import get_valid_token
from stocks.models import Info, Sector
from stocks.logger import StockLogger


class Command(BaseCommand):
    help = '''
    종목-업종 매핑 데이터 저장 (업종별주가요청 - ka20002)

    ※ 동작 방식:
    1. Sector 테이블에서 모든 고유한 (업종코드, 시장) 조합 가져오기
    2. 각 업종별로 ka20002 API 호출
    3. Info.sectors에 매핑 (ManyToMany 관계 연결)

    ※ 실행 순서:
    1. python manage.py save_sector --mode all  (먼저 실행)
    2. python manage.py save_stock_sector  (이 명령어)
    '''

    def add_arguments(self, parser):
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        # 로거 초기화
        self.log = StockLogger(self.stdout, self.style, options, 'save_stock_sector')

        # 1. 토큰 가져오기
        token = get_valid_token()

        if not token:
            self.log.error('토큰이 없습니다. python manage.py get_token을 먼저 실행하세요.')
            return

        # 2. Sector 테이블 확인
        sector_count = Sector.objects.count()
        if sector_count == 0:
            self.log.error('Sector 테이블이 비어있습니다!')
            self.log.debug('먼저 python manage.py save_sector --mode all 실행')
            return

        self.log.debug(f'Sector 데이터 확인 완료 ({sector_count:,}개 레코드)')

        # 3. 고유한 (업종코드, 시장) 조합 가져오기
        sectors = Sector.objects.values('code', 'market').distinct().order_by('code', 'market')
        sectors_list = list(sectors)

        self.log.info(f'총 {len(sectors_list)}개 업종 발견')
        self.log.separator()

        # 4. 각 업종에 대해 API 호출 및 매핑
        self.process_all_sectors(token, sectors_list)

    def process_all_sectors(self, token, sectors_list):
        """모든 업종에 대해 API 호출하고 종목-업종 매핑"""
        total_count = len(sectors_list)
        success_count = 0
        fail_count = 0
        total_added = 0
        total_unchanged = 0

        for idx, sector_info in enumerate(sectors_list, start=1):
            sector_code = sector_info['code']
            market = sector_info['market']

            self.log.debug(f'[{idx}/{total_count}] 업종 {sector_code} ({market}) 처리 중...')

            # 시장 구분 변환 (KOSPI→0, KOSDAQ→1)
            mrkt_tp = '0' if market == 'KOSPI' else '1'

            # API 호출
            params = {
                'mrkt_tp': mrkt_tp,
                'inds_cd': sector_code,
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

            # Sector 객체 가져오기 (최신 날짜)
            sector = Sector.objects.filter(
                code=sector_code,
                market=market
            ).order_by('-date').first()

            if not sector:
                self.log.debug(f'  → Sector 객체 없음')
                fail_count += 1
                continue

            # 종목-업종 매핑
            added_count, unchanged_count = self.map_stocks_to_sector(stock_list, sector)
            total_added += added_count
            total_unchanged += unchanged_count
            success_count += 1

            if added_count > 0:
                self.log.info(f'[{sector.name}] 추가: {added_count}개, 변경없음: {unchanged_count}개')
            else:
                self.log.debug(f'  → 변경 없음 ({unchanged_count}개 종목)')

            # API 호출 제한 방지 (0.5초 대기)
            time.sleep(0.5)

        # 최종 결과
        self.log.separator()
        if total_added > 0:
            self.log.info(f'처리 완료! 추가: {total_added}개, 변경없음: {total_unchanged}개', success=True)
        else:
            self.log.info(f'처리 완료! 변경 없음 (총 {total_unchanged}개 종목)', success=True)

    def map_stocks_to_sector(self, stock_list, sector):
        """종목 리스트와 업종을 매핑"""
        added_count = 0
        unchanged_count = 0

        for stock_data in stock_list:
            stock_code = stock_data.get('stk_cd')

            if not stock_code:
                continue

            try:
                info = Info.objects.get(code=stock_code)

                # 이미 매핑되어 있는지 확인
                if sector in info.sectors.all():
                    unchanged_count += 1
                else:
                    info.sectors.add(sector)
                    added_count += 1
                    self.log.info(f'  + {info.name}({stock_code}) → {sector.name}')

            except Info.DoesNotExist:
                pass
            except Exception as e:
                self.log.error(f'매핑 실패 ({stock_code}): {str(e)}')

        return added_count, unchanged_count

    def find_data_key(self, response_data):
        """응답에서 데이터 배열 키 찾기"""
        for key in ['inds_stkpc', 'data', 'result', 'output']:
            if key in response_data and isinstance(response_data[key], list):
                return key
        return None

    def call_api(self, token, data):
        """업종별주가요청 API 호출"""
        host = 'https://api.kiwoom.com'
        endpoint = '/api/dostk/sect'
        url = host + endpoint

        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'authorization': f'Bearer {token}',
            'api-id': 'ka20002',
        }

        try:
            response = requests.post(url, headers=headers, json=data)

            if response.status_code != 200:
                return None

            response_data = response.json()

            return response_data

        except Exception:
            return None
