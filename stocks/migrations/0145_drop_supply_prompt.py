from django.db import migrations


def drop_old(apps, schema_editor):
    """
    저장돼 있던 수급 프롬프트를 지운다. 코드 기본값이 대신 쓰인다.

    수급 프롬프트의 입력값을 통째로 바꿨다({외국인누적}·{일별수급데이터} ->
    {수급요약}·{투자자별}·{읽는법} 등). 저장된 옛 프롬프트가 있으면 그것이
    이기므로, 복사해도 없는 변수가 그대로 남는다. 지워서 새 기본값
    (prompts.SUPPLY_PROMPT_DEFAULT)이 쓰이게 한다.

    앞으로 화면에서 고친 값은 다시 이 자리에 저장된다.
    """
    SystemSetting = apps.get_model('stocks', 'SystemSetting')
    removed = SystemSetting.objects.filter(key='prompt_supply_demand_analysis').delete()
    print(f'  옛 수급 프롬프트 {removed[0]}건 제거 — 코드 기본값을 쓴다')


def noop(apps, schema_editor):
    """되돌릴 수 없다 — 지운 내용을 남기지 않는다."""


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0144_ai_note'),
    ]

    operations = [
        migrations.RunPython(drop_old, noop),
    ]
