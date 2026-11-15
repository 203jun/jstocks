# 시장 매매동향에서 안 쓰는 것들을 걷는다.
#
# 기관 세부 일곱 항목은 화면 어디에서도 읽지 않는다. 데이터를 받아오던
# 네이버 주소가 410 으로 사라진 뒤로는 채워지지도 않는다.
#
# 선물(FUTURES)도 같이 지운다. 수집만 하고 보는 곳이 없었다.

from django.db import migrations, models


def delete_futures(apps, schema_editor):
    MarketTrend = apps.get_model('stocks', 'MarketTrend')
    MarketTrend.objects.filter(market='FUTURES').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0163_remove_info_is_shared_alter_info_interest_level'),
    ]

    operations = [
        # 컬럼을 지우기 전에 행부터 지운다. SQLite 는 컬럼 제거를 테이블
        # 재작성으로 처리하므로 옮길 행이 적을수록 좋다.
        migrations.RunPython(delete_futures, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='markettrend',
            name='bank',
        ),
        migrations.RemoveField(
            model_name='markettrend',
            name='financial_investment',
        ),
        migrations.RemoveField(
            model_name='markettrend',
            name='insurance',
        ),
        migrations.RemoveField(
            model_name='markettrend',
            name='other_corporation',
        ),
        migrations.RemoveField(
            model_name='markettrend',
            name='other_financial',
        ),
        migrations.RemoveField(
            model_name='markettrend',
            name='pension_fund',
        ),
        migrations.RemoveField(
            model_name='markettrend',
            name='trust',
        ),
        migrations.AlterField(
            model_name='marketindicator',
            name='foreign_net_20d',
            field=models.BigIntegerField(blank=True, help_text='단위: 억원 (MarketTrend 최근 20영업일 합)', null=True, verbose_name='외국인 20일 누적 순매수'),
        ),
        migrations.AlterField(
            model_name='markettrend',
            name='foreign',
            field=models.BigIntegerField(help_text='외국인 순매수 (억원)', verbose_name='외국인'),
        ),
        migrations.AlterField(
            model_name='markettrend',
            name='individual',
            field=models.BigIntegerField(help_text='개인 순매수 (억원)', verbose_name='개인'),
        ),
        migrations.AlterField(
            model_name='markettrend',
            name='institution',
            field=models.BigIntegerField(help_text='기관 전체 순매수 (억원)', verbose_name='기관계'),
        ),
        migrations.AlterField(
            model_name='markettrend',
            name='market',
            field=models.CharField(db_index=True, help_text='KOSPI, KOSDAQ', max_length=10, verbose_name='시장'),
        ),
    ]
