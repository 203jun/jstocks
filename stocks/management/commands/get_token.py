import requests
import json
from pathlib import Path
from django.core.management.base import BaseCommand
from decouple import config


class Command(BaseCommand):
    help = 'API 토큰 발급 및 저장'

    def handle(self, *args, **options):
        # 1. 토큰 발급
        token_data = self.issue_token()

        if token_data:
            # 2. JSON 파일로 저장
            self.save_token(token_data)
            self.stdout.write(self.style.SUCCESS(f'토큰 발급 완료: {token_data["expires_dt"]}까지 유효'))
        else:
            self.stdout.write(self.style.ERROR('토큰 발급 실패'))

    def issue_token(self):
        """API 토큰 발급"""
        # 1. 요청할 API URL
        host = 'https://api.kiwoom.com'  # 실전투자
        # host = 'https://mockapi.kiwoom.com'  # 모의투자
        endpoint = '/oauth2/token'
        url = host + endpoint

        # 2. header 데이터
        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
        }

        # 3. 요청 데이터
        params = {
            'grant_type': 'client_credentials',
            'appkey': config('APPKEY'),
            'secretkey': config('SECRETKEY'),
        }

        try:
            # 4. http POST 요청
            response = requests.post(url, headers=headers, json=params)

            # 5. 응답 확인
            self.stdout.write(f'응답 코드: {response.status_code}')

            if response.status_code == 200:
                data = response.json()
                if data.get('return_code') == 0:
                    return {
                        'token': data['token'],
                        'expires_dt': data['expires_dt'],
                        'token_type': data['token_type'],
                    }
                else:
                    self.stdout.write(self.style.ERROR(f'API 에러: {data.get("return_msg")}'))
            else:
                self.stdout.write(self.style.ERROR(f'HTTP 에러: {response.status_code}'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'요청 실패: {str(e)}'))

        return None

    def save_token(self, token_data):
        """토큰을 JSON 파일로 저장"""
        # 프로젝트 루트 디렉토리에 저장
        token_file = Path(__file__).resolve().parent.parent.parent.parent / 'token.json'

        try:
            with open(token_file, 'w', encoding='utf-8') as f:
                json.dump(token_data, f, ensure_ascii=False, indent=4)
            self.stdout.write(f'토큰 저장 완료: {token_file}')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'토큰 저장 실패: {str(e)}'))
