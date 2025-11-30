"""
주식 데이터 수집 로거 모듈

로그 레벨:
- DEBUG: 상세 진행 상황 (API 파라미터, 루프 상태, 배치 수 등)
- INFO: 주요 결과 (시작/완료, 통계 요약)
- ERROR: 심각한 오류 (API 실패, DB 저장 실패)

사용법:
    from stocks.logger import StockLogger

    class Command(BaseCommand):
        def add_arguments(self, parser):
            StockLogger.add_arguments(parser)

        def handle(self, *args, **options):
            logger = StockLogger(self.stdout, self.style, options, 'save_daily_chart')
            logger.info('작업 시작')
            logger.debug('상세 정보...')
            logger.error('오류 발생!')
"""
import logging
from pathlib import Path
from datetime import datetime


class StockLogger:
    """Django Management Command용 로거"""

    # 로그 레벨 상수
    DEBUG = 0
    INFO = 1
    ERROR = 2

    LEVEL_MAP = {
        'debug': DEBUG,
        'info': INFO,
        'error': ERROR,
    }

    def __init__(self, stdout, style, options, command_name):
        """
        Args:
            stdout: Command의 self.stdout
            style: Command의 self.style
            options: Command options (--log-level 포함)
            command_name: 커맨드 이름 (파일 로깅용)
        """
        self.stdout = stdout
        self.style = style
        self.command_name = command_name

        # 콘솔 로그 레벨 설정
        level_str = options.get('log_level', 'debug')
        self.console_level = self.LEVEL_MAP.get(level_str, self.DEBUG)

        # 파일 로거 설정 (INFO, ERROR만 기록)
        self.file_logger = self._setup_file_logger()

    def _setup_file_logger(self):
        """파일 로거 설정"""
        # logs 디렉토리 생성
        log_dir = Path(__file__).resolve().parent.parent / 'logs'
        log_dir.mkdir(exist_ok=True)

        log_file = log_dir / 'stocks.log'

        # 로거 생성
        logger = logging.getLogger('stocks')
        logger.setLevel(logging.INFO)

        # 이미 핸들러가 있으면 추가하지 않음
        if not logger.handlers:
            # 파일 핸들러 설정
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(logging.INFO)

            # 포맷 설정
            formatter = logging.Formatter(
                '[%(asctime)s] [%(levelname)s] %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

        return logger

    @staticmethod
    def add_arguments(parser):
        """Command의 add_arguments에서 호출"""
        parser.add_argument(
            '--log-level',
            type=str,
            choices=['debug', 'info', 'error'],
            default='debug',
            dest='log_level',
            help='로그 레벨: debug(모든 로그), info(주요 결과만), error(에러만)'
        )

    def debug(self, msg):
        """
        DEBUG 레벨 로그

        용도: 상세한 진행 상황
        - API 호출 파라미터
        - 루프 카운트, 배치 데이터 개수
        - 필터링 결과
        - 연속조회 상태

        파일 기록: X
        """
        if self.console_level <= self.DEBUG:
            self.stdout.write(msg)

    def info(self, msg, success=False):
        """
        INFO 레벨 로그

        용도: 주요 결과
        - 시작/완료 메시지
        - 최종 통계 (신규 N개, 업데이트 M개)
        - 중요한 상태 변경

        Args:
            msg: 로그 메시지
            success: True면 녹색(SUCCESS) 스타일 적용

        파일 기록: O
        """
        if self.console_level <= self.INFO:
            if success:
                self.stdout.write(self.style.SUCCESS(msg))
            else:
                self.stdout.write(msg)

        # 파일에 기록
        self.file_logger.info(f'{self.command_name}: {msg}')

    def error(self, msg):
        """
        ERROR 레벨 로그

        용도: 심각한 오류
        - API 호출 실패
        - DB 저장 실패
        - 예외 발생

        파일 기록: O
        """
        if self.console_level <= self.ERROR:
            self.stdout.write(self.style.ERROR(msg))

        # 파일에 기록
        self.file_logger.error(f'{self.command_name}: {msg}')

    def warning(self, msg):
        """
        WARNING 레벨 로그 (콘솔만, 파일 기록 X)

        용도: 경고 메시지
        - 데이터 없음
        - 부분 실패
        """
        if self.console_level <= self.INFO:
            self.stdout.write(self.style.WARNING(msg))

    def separator(self, char='=', length=70):
        """구분선 출력 (DEBUG 레벨)"""
        self.debug(char * length)

    def header(self, title):
        """섹션 헤더 출력 (DEBUG 레벨)"""
        self.debug(f'\n[ {title} ]')
