from django.db import migrations


# (계좌 키, 계좌명, 정렬순서) — 키는 .env의 APPKEY_<KEY> / SECRETKEY_<KEY>와 짝이다
SUB_ACCOUNTS = [
    ('sub1', '부계좌', 1),
    ('sub2', 'ISA', 2),
]


def add_sub_accounts(apps, schema_editor):
    """자산 페이지에 표시할 보조 계좌를 등록한다 (수집은 ka01690 자산 스냅샷만)."""
    Account = apps.get_model('stocks', 'Account')

    for key, name, order in SUB_ACCOUNTS:
        Account.objects.get_or_create(
            key=key,
            defaults={'name': name, 'is_primary': False, 'is_active': True, 'order': order},
        )


def remove_sub_accounts(apps, schema_editor):
    """되돌리면 해당 계좌의 스냅샷·보유종목도 CASCADE로 함께 삭제된다."""
    Account = apps.get_model('stocks', 'Account')
    Account.objects.filter(key__in=[key for key, _, _ in SUB_ACCOUNTS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0134_account_required'),
    ]

    operations = [
        migrations.RunPython(add_sub_accounts, remove_sub_accounts),
    ]
