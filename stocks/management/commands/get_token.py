from django.core.management.base import BaseCommand
from stocks.utils import issue_token, save_token
from stocks.logger import StockLogger


class Command(BaseCommand):
    help = 'API 토큰 발급 및 저장'

    def add_arguments(self, parser):
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        # 로거 초기화
        self.log = StockLogger(self.stdout, self.style, options, 'get_token')

        # 토큰 발급 (항상 새로 발급)
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
