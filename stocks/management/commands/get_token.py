from django.core.management.base import BaseCommand
from stocks.utils import issue_token, save_token, send_telegram_error, get_active_account_keys
from stocks.logger import StockLogger


class Command(BaseCommand):
    help = '''
API 토큰 발급 및 저장 (계좌별)

옵션:
  --account   (선택) 계좌 키. 생략 시 활성 계좌 전체
  --log-level (선택) debug / info / warning / error (기본값: info)

예시:
  python manage.py get_token
  python manage.py get_token --account sub1
'''

    def add_arguments(self, parser):
        parser.add_argument(
            '--account',
            type=str,
            default=None,
            help='계좌 키 (생략 시 활성 계좌 전체)',
        )
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        # 로거 초기화
        self.log = StockLogger(self.stdout, self.style, options, 'get_token')

        account_key = options.get('account')
        account_keys = [account_key] if account_key else get_active_account_keys()

        failed = []
        for key in account_keys:
            if not self.issue_for(key):
                failed.append(key)

        if failed:
            send_telegram_error('get_token', f'토큰 발급 실패: {", ".join(failed)}')

    def issue_for(self, account_key):
        """계좌 1개 토큰 발급 + 저장. 성공 여부 반환"""
        self.log.debug(f'[{account_key}] 토큰 발급 중...')
        token_data = issue_token(account_key)

        if not token_data:
            self.log.error(f'[{account_key}] 토큰 발급 실패')
            return False

        if not save_token(token_data, account_key):
            self.log.error(f'[{account_key}] 토큰 저장 실패')
            return False

        self.log.info(
            f'[{account_key}] 토큰 발급 완료: {token_data["expires_dt"]}까지 유효',
            success=True,
        )
        return True
