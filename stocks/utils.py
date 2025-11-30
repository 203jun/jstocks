import json
import logging
import requests
from pathlib import Path
from datetime import datetime
from decouple import config


def _get_file_logger():
    """파일 로거 가져오기"""
    log_dir = Path(__file__).resolve().parent.parent / 'logs'
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / 'stocks.log'

    logger = logging.getLogger('stocks.utils')
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        formatter = logging.Formatter(
            '[%(asctime)s] [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


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
        _get_file_logger().error('utils: 토큰 파일이 없습니다')
        return None
    except Exception as e:
        _get_file_logger().error(f'utils: 토큰 조회 실패 - {str(e)}')
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
            _get_file_logger().error(f'utils: 토큰 만료 (만료 시간: {expires_dt})')
            return False

        return True

    except Exception as e:
        _get_file_logger().error(f'utils: 토큰 유효성 확인 실패 - {str(e)}')
        return False


def issue_token():
    """
    API에서 새 토큰을 발급받습니다.

    Returns:
        dict: 토큰 정보 {'token': str, 'expires_dt': str, 'token_type': str}
        None: 발급 실패 시
    """
    logger = _get_file_logger()

    host = 'https://api.kiwoom.com'
    endpoint = '/oauth2/token'
    url = host + endpoint

    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
    }

    params = {
        'grant_type': 'client_credentials',
        'appkey': config('APPKEY'),
        'secretkey': config('SECRETKEY'),
    }

    try:
        response = requests.post(url, headers=headers, json=params)

        if response.status_code == 200:
            data = response.json()
            if data.get('return_code') == 0:
                token_data = {
                    'token': data['token'],
                    'expires_dt': data['expires_dt'],
                    'token_type': data['token_type'],
                }
                logger.info(f'utils: 토큰 발급 완료 (만료: {data["expires_dt"]})')
                return token_data
            else:
                logger.error(f'utils: 토큰 발급 API 에러 - {data.get("return_msg")}')
        else:
            logger.error(f'utils: 토큰 발급 HTTP 에러 - {response.status_code}')

    except Exception as e:
        logger.error(f'utils: 토큰 발급 실패 - {str(e)}')

    return None


def save_token(token_data):
    """
    토큰을 JSON 파일로 저장합니다.

    Args:
        token_data: 토큰 정보 dict

    Returns:
        bool: 저장 성공 여부
    """
    token_file = Path(__file__).resolve().parent.parent / 'token.json'

    try:
        with open(token_file, 'w', encoding='utf-8') as f:
            json.dump(token_data, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        _get_file_logger().error(f'utils: 토큰 저장 실패 - {str(e)}')
        return False


def refresh_token():
    """
    토큰을 갱신합니다. (발급 + 저장)

    Returns:
        str: 새 토큰 문자열
        None: 갱신 실패 시
    """
    token_data = issue_token()

    if token_data:
        if save_token(token_data):
            return token_data.get('token')

    return None


def get_valid_token():
    """
    유효한 토큰을 반환합니다.
    토큰이 없거나 만료된 경우 자동으로 갱신합니다.

    Returns:
        str: 유효한 토큰 문자열
        None: 토큰 발급 실패 시
    """
    # 1. 기존 토큰이 유효하면 그대로 반환
    if is_token_valid():
        token_data = get_token()
        return token_data.get('token') if token_data else None

    # 2. 토큰이 없거나 만료되었으면 자동 갱신
    _get_file_logger().info('utils: 토큰 만료/없음 - 자동 갱신 시도')
    return refresh_token()
