from django.core.management.base import BaseCommand
from stocks.utils import send_telegram_message


class Command(BaseCommand):
    help = '텔레그램 Bot API 테스트'

    def add_arguments(self, parser):
        parser.add_argument(
            '--message', '-m',
            type=str,
            default='테스트 메시지입니다.',
            help='전송할 메시지 (기본: "테스트 메시지입니다.")'
        )

    def handle(self, *args, **options):
        message = options['message']

        self.stdout.write(f'전송할 메시지: {message}')
        self.stdout.write('-' * 50)

        result = send_telegram_message(message)

        if result:
            self.stdout.write(self.style.SUCCESS('전송 성공!'))
        else:
            self.stdout.write(self.style.ERROR('전송 실패. .env 설정을 확인하세요.'))
            self.stdout.write('필요한 환경변수:')
            self.stdout.write('  - TELEGRAM_BOT_TOKEN')
            self.stdout.write('  - TELEGRAM_CHAT_ID')
