# -*- coding: utf-8 -*-
from django.core.management.base import BaseCommand, CommandError

from stocks.claude_cli import ClaudeAuthFailed, ClaudeFailed, ask
from stocks.logger import StockLogger


class Command(BaseCommand):
    help = '''
Claude 로그인이 살아 있는지 확인 (배치 맨 앞에서 한 번)

구독 인증은 몇 달을 가다가 어느 날 끊긴다 — 비밀번호 변경, 다른 기기에서
전체 로그아웃, 구독 변경. 날짜를 예측할 수 없다.

80종목을 다 돌린 뒤에 "사실 인증이 끊겨 있었다"를 아는 것보다, 맨 앞에서
한 마디 찔러보고 텔레그램을 받는 편이 낫다.

예시:
  python manage.py check_claude_auth
'''

    def add_arguments(self, parser):
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        log = StockLogger(self.stdout, self.style, options, 'check_claude_auth')

        try:
            # 되도록 짧게 묻는다. 시스템 프롬프트 1만 토큰은 어차피 따라붙지만
            # 캐시에 올려 두면 뒤따르는 진짜 호출이 그것을 읽는다.
            answer = ask('OK 라고만 답해라.', timeout=120)
        except ClaudeAuthFailed as e:
            log.error(f'Claude 로그인이 풀렸습니다: {e}')
            raise CommandError(
                'Claude 재로그인이 필요합니다. 서버에서: sudo -u stock claude login'
            )
        except ClaudeFailed as e:
            log.error(f'Claude 호출 실패: {e}')
            raise CommandError(f'Claude 호출 실패: {e}')

        log.info(f'Claude 응답 확인: {answer["text"][:60]}', success=True)
