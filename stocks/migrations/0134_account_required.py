import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """0133에서 기존 행을 모두 주계좌에 귀속시킨 뒤 account를 필수로 전환한다."""

    dependencies = [
        ('stocks', '0133_backfill_primary_account'),
    ]

    operations = [
        migrations.AlterField(
            model_name='dailyaccountsnapshot',
            name='account',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='snapshots',
                to='stocks.account',
                verbose_name='계좌',
            ),
        ),
        migrations.AlterField(
            model_name='holding',
            name='account',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='holdings',
                to='stocks.account',
                verbose_name='계좌',
            ),
        ),
    ]
