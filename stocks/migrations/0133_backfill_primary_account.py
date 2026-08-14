from django.db import migrations


def create_primary_account(apps, schema_editor):
    """기존 단일 계좌 데이터를 주계좌(main)에 귀속시킨다."""
    Account = apps.get_model('stocks', 'Account')
    DailyAccountSnapshot = apps.get_model('stocks', 'DailyAccountSnapshot')
    Holding = apps.get_model('stocks', 'Holding')

    account, _ = Account.objects.get_or_create(
        key='main',
        defaults={'name': '주계좌', 'is_primary': True, 'is_active': True, 'order': 0},
    )

    DailyAccountSnapshot.objects.filter(account__isnull=True).update(account=account)
    Holding.objects.filter(account__isnull=True).update(account=account)


def remove_primary_account(apps, schema_editor):
    """되돌릴 때는 FK만 비운다 (데이터 자체는 보존)."""
    Account = apps.get_model('stocks', 'Account')
    DailyAccountSnapshot = apps.get_model('stocks', 'DailyAccountSnapshot')
    Holding = apps.get_model('stocks', 'Holding')

    DailyAccountSnapshot.objects.update(account=None)
    Holding.objects.update(account=None)
    Account.objects.filter(key='main').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0132_add_account'),
    ]

    operations = [
        migrations.RunPython(create_primary_account, remove_primary_account),
    ]
