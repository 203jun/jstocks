from decimal import Decimal

from django.db import migrations


def clean(apps, schema_editor):
    """
    칼럼에 담기지 않는 Decimal 값을 비우고, 그 때문에 남은 빈 껍데기를 지운다.

    제일바이오(052670)가 키움에서 등락률 29948.08 을 받았다. DecimalField(6,2)의
    한계는 9999.99 라 저장은 됐지만 읽을 때 decimal.InvalidOperation 이 났고,
    그 종목 상세 페이지가 500 으로 죽었다. 여러 종목을 한 번에 읽는 화면도 이
    한 행 때문에 같이 넘어간다.

    들어오는 쪽은 save_stock_info._parse_decimal 에서 막았다. 여기서는 이미
    들어온 값을 치운다.

    삭제 대상은 '값을 비운 종목' 중에서만 고른다. 비활성 종목 전체를 훑으면
    지울 이유가 없는 것까지 후보에 들어온다.
    """
    Info = apps.get_model('stocks', 'Info')
    cursor = schema_editor.connection.cursor()

    # 값을 Python 으로 읽는 순간 터지므로 raw SQL 로 훑는다.
    suspects = set()
    for f in Info._meta.get_fields():
        if getattr(f, 'get_internal_type', lambda: '')() != 'DecimalField':
            continue
        # 한계값은 float 로 넘긴다. 문자열로 주면 sqlite 가 숫자와 문자열을
        # 비교하게 되고, 그 경우 문자열이 늘 크다고 판정해 아무것도 안 걸린다.
        limit = float(Decimal(10) ** (f.max_digits - f.decimal_places))
        cursor.execute(
            f'SELECT code FROM info WHERE {f.column} IS NOT NULL '
            f'AND ABS({f.column}) >= %s', [limit])
        codes = [r[0] for r in cursor.fetchall()]
        if not codes:
            continue
        marks = ','.join(['%s'] * len(codes))
        cursor.execute(f'UPDATE info SET {f.column} = NULL WHERE code IN ({marks})', codes)
        suspects.update(codes)
        print(f'  {f.column} 범위 초과 {len(codes)}건 비움: {", ".join(codes)}')

    if not suspects:
        print('  범위를 벗어난 값 없음')
        return

    # 종목을 가리키는 모델을 모아둔다. 그중 하나라도 행이 있으면 껍데기가 아니다.
    related = [m for m in apps.get_app_config('stocks').get_models()
               if any(getattr(f, 'name', None) == 'stock' and f.is_relation
                      for f in m._meta.get_fields())]

    removed = 0
    for stock in Info.objects.filter(code__in=suspects,
                                     is_active=False, interest_level__isnull=True):
        if any(m.objects.filter(stock_id=stock.code).exists() for m in related):
            print(f'  남김(데이터 있음): {stock.code} {stock.name}')
            continue
        print(f'  빈 껍데기 삭제: {stock.code} {stock.name}')
        stock.delete()
        removed += 1

    print(f'  정리 완료 — 값 비움 {len(suspects)}종목, 종목 삭제 {removed}건')


def noop(apps, schema_editor):
    """되돌릴 수 없다 — 지운 값이 무엇이었는지 남기지 않는다."""


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0141_infoetf_interest_level'),
    ]

    operations = [
        migrations.RunPython(clean, noop),
    ]
