from django.core.management.base import BaseCommand
from stocks.utils import issue_token, save_token, get_token, is_token_valid
from stocks.logger import StockLogger


class Command(BaseCommand):
    help = 'API 토큰 발급 및 저장'

    def add_arguments(self, parser):
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        # 로거 초기화
        self.log = StockLogger(self.stdout, self.style, options, 'get_token')

        # 1. 기존 토큰 확인
        if is_token_valid():
            existing = get_token()
            self.log.info(f'기존 토큰 유효 (만료: {existing["expires_dt"]})')
            self.log.debug('새 토큰을 강제로 발급받으려면 token.json을 삭제하세요.')
            return

        # 2. 토큰 발급
        self.log.debug('토큰 발급 중...')
        token_data = issue_token()

        if token_data:
            # 3. JSON 파일로 저장
            if save_token(token_data):
                self.log.info(f'토큰 발급 완료: {token_data["expires_dt"]}까지 유효', success=True)
            else:
                self.log.error('토큰 저장 실패')
        else:
            self.log.error('토큰 발급 실패')
