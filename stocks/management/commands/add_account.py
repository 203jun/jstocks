from django.core.management.base import BaseCommand
from django.db import transaction
from stocks.models import Account
from stocks.utils import get_api_credentials
from stocks.logger import StockLogger


class Command(BaseCommand):
    help = '''
계좌 등록 / 수정 (자산 페이지 계좌 탭)

계좌 키(key)는 .env의 APPKEY_<KEY> / SECRETKEY_<KEY> 및 토큰 파일명과
연결된다. 주계좌(main)만 예외적으로 APPKEY / SECRETKEY, token.json을 쓴다.

옵션:
  --key       (필수) 계좌 키 (영문 소문자/숫자, 예: sub1)
  --name      (필수) 화면에 표시할 계좌명
  --order     (선택) 탭 정렬 순서 (기본값: 등록 순)
  --primary   (선택) 주계좌로 지정 (기존 주계좌는 해제됨)
  --inactive  (선택) 비활성으로 등록 (수집·화면에서 제외)
  --log-level (선택) debug / info / warning / error (기본값: info)

예시:
  python manage.py add_account --key sub1 --name "연금계좌"
  python manage.py add_account --key sub2 --name "ISA" --order 2
'''

    def add_arguments(self, parser):
        parser.add_argument('--key', type=str, required=True, help='계좌 키 (예: sub1)')
        parser.add_argument('--name', type=str, required=True, help='계좌명')
        parser.add_argument('--order', type=int, default=None, help='탭 정렬 순서')
        parser.add_argument('--primary', action='store_true', help='주계좌로 지정')
        parser.add_argument('--inactive', action='store_true', help='비활성으로 등록')
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        self.log = StockLogger(self.stdout, self.style, options, 'add_account')

        key = options['key'].strip().lower()
        name = options['name'].strip()
        is_primary = options['primary']

        order = options['order']
        if order is None:
            order = Account.objects.count()

        # .env에 키가 있는지 먼저 확인 (없으면 수집 때 조용히 실패한다)
        appkey, _ = get_api_credentials(key)
        if not appkey:
            suffix = 'APPKEY / SECRETKEY' if key == 'main' else f'APPKEY_{key.upper()} / SECRETKEY_{key.upper()}'
            self.log.warning(f'.env에 {suffix} 가 없습니다. 등록은 진행하지만 수집 전에 반드시 추가하세요.')

        with transaction.atomic():
            if is_primary:
                Account.objects.filter(is_primary=True).exclude(key=key).update(is_primary=False)

            account, created = Account.objects.update_or_create(
                key=key,
                defaults={
                    'name': name,
                    'order': order,
                    'is_active': not options['inactive'],
                    **({'is_primary': True} if is_primary else {}),
                },
            )

        action = '등록' if created else '수정'
        self.log.info(
            f'{action} 완료 | {account.name}({account.key}) | '
            f'{"주계좌" if account.is_primary else "보조계좌"} | '
            f'{"활성" if account.is_active else "비활성"} | 정렬 {account.order}',
            success=True,
        )

        if created:
            self.log.info(f'다음 단계: python manage.py get_token --account {key}')
