"""
장 운영일 체크 명령어

오늘이 장이 열린 날인지 확인합니다.
삼성전자(005930)의 오늘 일봉 데이터가 있으면 장이 열린 것으로 판단합니다.

사용법:
  python manage.py check_market_open

반환값:
  - 장 운영일: exit code 0 (성공)
  - 휴장일: exit code 1 (실패)

daily_update.sh에서 사용 예시:
  python manage.py check_market_open || exit 0
"""

import sys
import requests
from datetime import datetime
from django.core.management.base import BaseCommand
from stocks.utils import get_valid_token


class Command(BaseCommand):
    help = '오늘이 장 운영일인지 확인 (휴장일이면 exit 1)'

    def handle(self, *args, **options):
        today = datetime.now().strftime('%Y-%m-%d')
        self.stdout.write(f'[{today}] 장 운영일 체크...')

        # 토큰 가져오기
        token = get_valid_token()
        if not token:
            self.stdout.write(self.style.ERROR('토큰이 없습니다.'))
            sys.exit(1)

        # 삼성전자(005930) 오늘 데이터 조회
        is_open = self.check_today_data(token)

        if is_open:
            self.stdout.write(self.style.SUCCESS('장 운영일입니다. 스크립트를 계속 실행합니다.'))
            sys.exit(0)
        else:
            self.stdout.write(self.style.WARNING('휴장일입니다. 스크립트를 종료합니다.'))
            sys.exit(1)

    def check_today_data(self, token):
        """삼성전자 오늘 일봉 데이터가 있는지 확인"""
        today = datetime.now().strftime('%Y%m%d')

        url = 'https://api.kiwoom.com/api/dostk/chart'
        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'authorization': f'Bearer {token}',
            'cont-yn': 'N',
            'next-key': '',
            'api-id': 'ka10081',
        }
        data = {
            'stk_cd': '005930',  # 삼성전자
            'base_dt': today,
            'upd_stkpc_tp': '1',
        }

        try:
            response = requests.post(url, headers=headers, json=data, timeout=10)
            if response.status_code != 200:
                self.stdout.write(f'API 호출 실패: {response.status_code}')
                return False

            response_data = response.json()

            # 데이터 배열 찾기
            data_key = None
            for key in ['stk_dt_pole_chart_qry', 'stk_daly_chart', 'chart', 'data', 'result', 'output']:
                if key in response_data and isinstance(response_data[key], list):
                    data_key = key
                    break

            if not data_key or not response_data[data_key]:
                return False

            # 오늘 날짜 데이터가 있는지 확인
            for item in response_data[data_key]:
                if item.get('dt') == today:
                    return True

            return False

        except Exception as e:
            self.stdout.write(f'API 호출 오류: {str(e)}')
            return False
