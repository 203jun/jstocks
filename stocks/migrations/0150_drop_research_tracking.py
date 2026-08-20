# -*- coding: utf-8 -*-
"""
리서치의 '트래킹' 칸을 없앤다.

'계속 업데이트할 질문'을 표시해 두면 일반 목록에서 위로 올려주는 값이었다.
272건 중 한 건도 켜진 적이 없다(섹터 리서치도 0건). 켜도 하는 일이 목록
순서를 바꾸는 것뿐이라 켤 이유가 없었다.

종목의 '추적중'(Info.is_tracking, 목록의 👀)은 이름만 같고 다른 기능이다.
그쪽은 실제로 쓰고 있으므로 건드리지 않는다.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0149_drop_research_opinion'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='sectorquestionreport',
            name='is_tracking',
        ),
        migrations.RemoveField(
            model_name='stockquestionreport',
            name='is_tracking',
        ),
    ]
