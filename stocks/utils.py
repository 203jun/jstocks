import json
from pathlib import Path
from datetime import datetime


def get_token():
    """
    저장된 API 토큰을 조회합니다.

    Returns:
        dict: 토큰 정보 {'token': str, 'expires_dt': str, 'token_type': str}
        None: 토큰 파일이 없거나 오류 발생 시
    """
    token_file = Path(__file__).resolve().parent.parent / 'token.json'

    try:
        with open(token_file, 'r', encoding='utf-8') as f:
            token_data = json.load(f)
        return token_data
    except FileNotFoundError:
        print('토큰 파일이 없습니다. python manage.py get_token을 먼저 실행하세요.')
        return None
    except Exception as e:
        print(f'토큰 조회 실패: {str(e)}')
        return None


def is_token_valid():
    """
    토큰이 유효한지 확인합니다.

    Returns:
        bool: 토큰이 유효하면 True, 아니면 False
    """
    token_data = get_token()

    if not token_data:
        return False

    try:
        # expires_dt 형식: "20251130192940" (YYYYMMDDHHmmss)
        expires_dt = token_data.get('expires_dt')
        if not expires_dt:
            return False

        # 문자열을 datetime으로 변환
        expire_time = datetime.strptime(expires_dt, '%Y%m%d%H%M%S')
        current_time = datetime.now()

        # 만료 시간과 현재 시간 비교
        if current_time >= expire_time:
            print(f'토큰이 만료되었습니다. (만료 시간: {expires_dt})')
            print('python manage.py get_token을 실행하여 토큰을 재발급하세요.')
            return False

        return True

    except Exception as e:
        print(f'토큰 유효성 확인 실패: {str(e)}')
        return False


def get_valid_token():
    """
    유효한 토큰을 반환합니다.

    Returns:
        str: 유효한 토큰 문자열
        None: 토큰이 없거나 만료된 경우
    """
    if is_token_valid():
        token_data = get_token()
        return token_data.get('token') if token_data else None
    return None
