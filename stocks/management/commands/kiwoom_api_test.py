# -*- coding: utf-8 -*-
import requests
import json
from datetime import datetime
from django.core.management.base import BaseCommand
from stocks.utils import get_valid_token


# API 정의
API_DEFINITIONS = {
    'ka10001': {
        'name': '종목정보',
        'endpoint': '/api/dostk/stkinfo',
        'params': {
            'stk_cd': {'desc': '종목코드', 'required': True, 'example': '005930'},
        },
    },
    'ka10014': {
        'name': '공매도',
        'endpoint': '/api/dostk/shsa',
        'params': {
            'stk_cd': {'desc': '종목코드', 'required': True, 'example': '005930'},
            'tm_tp': {'desc': '시간구분 (0:시작일, 1:기간)', 'required': True, 'default': '1'},
            'strt_dt': {'desc': '시작일 (YYYYMMDD)', 'required': True, 'example': '20241201'},
            'end_dt': {'desc': '종료일 (YYYYMMDD)', 'required': True, 'example': '20241205'},
        },
    },
    'ka10051': {
        'name': '업종별투자자순매수',
        'endpoint': '/api/dostk/sect',
        'params': {
            'mrkt_tp': {'desc': '시장구분 (0:코스피, 1:코스닥)', 'required': True, 'example': '0'},
            'amt_qty_tp': {'desc': '금액수량구분 (0:금액, 1:수량)', 'required': True, 'default': '0'},
            'base_dt': {'desc': '기준일자 (YYYYMMDD)', 'required': False, 'example': '20241205'},
            'stex_tp': {'desc': '거래소구분 (1:KRX, 2:NXT, 3:통합)', 'required': True, 'default': '1'},
        },
    },
    'ka10059': {
        'name': '종목별투자자동향',
        'endpoint': '/api/dostk/stkinfo',
        'params': {
            'dt': {'desc': '조회일자 (YYYYMMDD)', 'required': True, 'example': '20241205'},
            'stk_cd': {'desc': '종목코드', 'required': True, 'example': '005930'},
            'amt_qty_tp': {'desc': '금액수량구분 (1:금액, 2:수량)', 'required': True, 'default': '1'},
            'trde_tp': {'desc': '매매구분 (0:순매수, 1:매수, 2:매도)', 'required': True, 'default': '0'},
            'unit_tp': {'desc': '단위구분 (1000:천주, 1:단주)', 'required': True, 'default': '1000'},
        },
    },
    'ka10081': {
        'name': '일봉',
        'endpoint': '/api/dostk/chart',
        'params': {
            'stk_cd': {'desc': '종목코드', 'required': True, 'example': '005930'},
            'base_dt': {'desc': '기준일자 (YYYYMMDD)', 'required': True, 'example': '20241205'},
            'upd_stkpc_tp': {'desc': '수정주가구분 (0, 1)', 'required': True, 'default': '1'},
        },
    },
    'ka10082': {
        'name': '주봉',
        'endpoint': '/api/dostk/chart',
        'params': {
            'stk_cd': {'desc': '종목코드', 'required': True, 'example': '005930'},
            'base_dt': {'desc': '기준일자 (YYYYMMDD)', 'required': True, 'example': '20241205'},
            'upd_stkpc_tp': {'desc': '수정주가구분 (0, 1)', 'required': True, 'default': '1'},
        },
    },
    'ka10083': {
        'name': '월봉',
        'endpoint': '/api/dostk/chart',
        'params': {
            'stk_cd': {'desc': '종목코드', 'required': True, 'example': '005930'},
            'base_dt': {'desc': '기준일자 (YYYYMMDD)', 'required': True, 'example': '20241205'},
            'upd_stkpc_tp': {'desc': '수정주가구분 (0, 1)', 'required': True, 'default': '1'},
        },
    },
    'ka10099': {
        'name': '종목리스트',
        'endpoint': '/api/dostk/stkinfo',
        'params': {
            'mrkt_tp': {'desc': '시장구분 (0:코스피, 10:코스닥, 8:ETF, 50:코넥스, 3:ELW, 30:K-OTC)', 'required': True, 'example': '0'},
        },
    },
    'ka20002': {
        'name': '업종별주가(종목)',
        'endpoint': '/api/dostk/sect',
        'params': {
            'mrkt_tp': {'desc': '시장구분 (0:코스피, 1:코스닥, 2:코스피200)', 'required': True, 'example': '0'},
            'inds_cd': {'desc': '업종코드 (001:종합KOSPI, 002:대형주, 003:중형주, 004:소형주, 101:종합KOSDAQ, 201:KOSPI200, 302:KOSTAR, 701:KRX100)', 'required': True, 'example': '001'},
            'stex_tp': {'desc': '거래소구분 (1:KRX, 2:NXT, 3:통합)', 'required': True, 'default': '1'},
        },
    },
}


class Command(BaseCommand):
    help = '''
    키움 API 테스트 도구

    사용법:
      python manage.py kiwoom_api_test                    # API 목록 표시
      python manage.py kiwoom_api_test <api_id>           # API 상세 정보
      python manage.py kiwoom_api_test <api_id> <params>  # API 호출

    예시:
      python manage.py kiwoom_api_test ka10001 stk_cd=005930
      python manage.py kiwoom_api_test ka10051 mrkt_tp=0
      python manage.py kiwoom_api_test ka10081 stk_cd=005930 base_dt=20241205
    '''

    def add_arguments(self, parser):
        parser.add_argument(
            'api_id',
            nargs='?',
            help='API ID (예: ka10001, ka10051)'
        )
        parser.add_argument(
            'params',
            nargs='*',
            help='API 파라미터 (key=value 형식)'
        )
        parser.add_argument(
            '--raw',
            action='store_true',
            help='응답 전체 출력 (요약 없이)'
        )

    def handle(self, *args, **options):
        api_id = options.get('api_id')
        params = options.get('params', [])
        raw_output = options.get('raw', False)

        # 인자 없이 실행 → API 목록 표시
        if not api_id:
            self.show_api_list()
            return

        # API ID만 입력 → API 상세 정보
        api_id = api_id.lower()
        if api_id not in API_DEFINITIONS:
            self.stderr.write(self.style.ERROR(f'알 수 없는 API: {api_id}'))
            self.stderr.write('사용 가능한 API: ' + ', '.join(API_DEFINITIONS.keys()))
            return

        if not params:
            self.show_api_detail(api_id)
            return

        # 파라미터와 함께 → API 호출
        self.call_api(api_id, params, raw_output)

    def show_api_list(self):
        """API 목록 표시"""
        self.stdout.write(self.style.SUCCESS('\n=== 키움 API 목록 ===\n'))

        # 카테고리별 분류
        categories = {
            '종목정보': ['ka10001', 'ka10099'],
            '차트': ['ka10081', 'ka10082', 'ka10083'],
            '투자자': ['ka10059', 'ka10051'],
            '업종': ['ka20002'],
            '기타': ['ka10014'],
        }

        for category, apis in categories.items():
            self.stdout.write(self.style.WARNING(f'[{category}]'))
            for api_id in apis:
                if api_id in API_DEFINITIONS:
                    api = API_DEFINITIONS[api_id]
                    self.stdout.write(f'  {api_id}: {api["name"]}')
            self.stdout.write('')

        self.stdout.write(self.style.MIGRATE_HEADING('\n사용법:'))
        self.stdout.write('  python manage.py kiwoom_api_test <api_id>           # 상세 정보')
        self.stdout.write('  python manage.py kiwoom_api_test <api_id> <params>  # API 호출\n')

    def show_api_detail(self, api_id):
        """API 상세 정보 표시"""
        api = API_DEFINITIONS[api_id]

        self.stdout.write(self.style.SUCCESS(f'\n=== {api_id}: {api["name"]} ===\n'))
        self.stdout.write(f'엔드포인트: {api["endpoint"]}\n')
        self.stdout.write(self.style.WARNING('파라미터:'))

        for param_name, param_info in api['params'].items():
            required = '(필수)' if param_info.get('required') else '(선택)'
            default = f', 기본값: {param_info["default"]}' if 'default' in param_info else ''
            example = f', 예시: {param_info["example"]}' if 'example' in param_info else ''
            self.stdout.write(f'  {param_name}: {param_info["desc"]} {required}{default}{example}')

        # 예시 명령어 생성
        self.stdout.write(self.style.MIGRATE_HEADING('\n예시 명령어:'))
        example_cmd = f'python manage.py kiwoom_api_test {api_id}'
        for param_name, param_info in api['params'].items():
            if 'example' in param_info:
                example_cmd += f' {param_name}={param_info["example"]}'
            elif 'default' in param_info:
                example_cmd += f' {param_name}={param_info["default"]}'
        self.stdout.write(f'  {example_cmd}\n')

    def call_api(self, api_id, params_list, raw_output):
        """API 호출"""
        api = API_DEFINITIONS[api_id]

        # 토큰 확인
        token = get_valid_token()
        if not token:
            self.stderr.write(self.style.ERROR('토큰이 없습니다. python manage.py get_token을 먼저 실행하세요.'))
            return

        # 파라미터 파싱
        params = {}
        for p in params_list:
            if '=' in p:
                key, value = p.split('=', 1)
                params[key] = value
            else:
                self.stderr.write(self.style.ERROR(f'잘못된 파라미터 형식: {p} (key=value 형식으로 입력)'))
                return

        # 기본값 적용
        for param_name, param_info in api['params'].items():
            if param_name not in params and 'default' in param_info:
                params[param_name] = param_info['default']

        # 필수 파라미터 확인
        missing = []
        for param_name, param_info in api['params'].items():
            if param_info.get('required') and param_name not in params:
                missing.append(param_name)

        if missing:
            self.stderr.write(self.style.ERROR(f'필수 파라미터 누락: {", ".join(missing)}'))
            self.stdout.write('필요한 파라미터:')
            for m in missing:
                info = api['params'][m]
                self.stdout.write(f'  {m}: {info["desc"]}')
            return

        # API 호출
        self.stdout.write(self.style.SUCCESS(f'\n=== {api_id}: {api["name"]} 호출 ===\n'))
        self.stdout.write(f'엔드포인트: https://api.kiwoom.com{api["endpoint"]}')
        self.stdout.write(f'파라미터: {json.dumps(params, ensure_ascii=False)}')
        self.stdout.write('')

        url = f'https://api.kiwoom.com{api["endpoint"]}'
        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'authorization': f'Bearer {token}',
            'cont-yn': 'N',
            'next-key': '',
            'api-id': api_id,
        }

        try:
            response = requests.post(url, headers=headers, json=params)

            self.stdout.write(self.style.WARNING(f'응답 코드: {response.status_code}'))

            # 응답 헤더
            header_info = {
                'cont-yn': response.headers.get('cont-yn'),
                'next-key': response.headers.get('next-key', '')[:30] + '...' if response.headers.get('next-key') else '',
            }
            self.stdout.write(f'응답 헤더: {json.dumps(header_info, ensure_ascii=False)}')

            if response.status_code != 200:
                self.stderr.write(self.style.ERROR(f'API 오류: {response.text}'))
                return

            data = response.json()

            if raw_output:
                self.stdout.write(self.style.MIGRATE_HEADING('\n응답 데이터 (전체):'))
                self.stdout.write(json.dumps(data, indent=2, ensure_ascii=False))
            else:
                self.print_response_summary(data)

            self.stdout.write(self.style.SUCCESS('\nAPI 호출 완료!'))

        except Exception as e:
            self.stderr.write(self.style.ERROR(f'API 호출 실패: {str(e)}'))

    def print_response_summary(self, data):
        """응답 요약 출력"""
        self.stdout.write(self.style.MIGRATE_HEADING('\n응답 구조:'))
        self.stdout.write(f'최상위 키: {list(data.keys())}')

        # 데이터 배열 찾기
        data_key = None
        for key in data.keys():
            if isinstance(data[key], list) and len(data[key]) > 0:
                data_key = key
                break

        if data_key:
            items = data[data_key]
            self.stdout.write(f'\n데이터 키: {data_key}')
            self.stdout.write(f'데이터 수: {len(items)}개')

            if len(items) > 0:
                self.stdout.write(f'필드 목록: {list(items[0].keys())}')
                self.stdout.write(self.style.MIGRATE_HEADING('\n샘플 데이터 (처음 3개):'))
                self.stdout.write(json.dumps(items[:3], indent=2, ensure_ascii=False))
        else:
            self.stdout.write(self.style.MIGRATE_HEADING('\n응답 데이터:'))
            self.stdout.write(json.dumps(data, indent=2, ensure_ascii=False))
