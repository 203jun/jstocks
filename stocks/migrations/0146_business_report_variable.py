# -*- coding: utf-8 -*-
"""
기업분석 프롬프트에서 "첨부된 사업보고서" 를 {사업보고서} 로 바꾼다.

지금까지는 프롬프트를 복사한 뒤 DART 에서 PDF 를 내려받아 claude.ai 에
첨부해야 했다. 이제 프롬프트 버튼을 누르면 화면이 절 본문을 받아 채운다.

문구가 종목마다가 아니라 프롬프트마다 하나씩만 있어 기계로 바꿀 수 있다.
바꾼 것·못 바꾼 것을 다 찍는다 — 상용 프롬프트가 조금 달라 패턴이 어긋나면
조용히 넘어가는 대신 눈에 보여야 한다.
"""
import re

from django.db import migrations

# 프롬프트 이름 -> (붙일 절, 절이 없어 새로 만들 때 덧붙일 안내)
# 절이 빈 값이면 II. 사업의 내용. 이름이 상용·로컬에서 갈린 것도 같이 적어 둔다.
_COMPETE_HINT = '시장점유율·경쟁요소·생산능력·연구개발활동 부분을 특히 참고해줘.'
SECTION_SPEC = {
    '사업모델': ('', ''),
    '수익구조': ('', ''),
    '경쟁력': ('', _COMPETE_HINT),
    '수주잔고': ('', '"매출 및 수주상황" 부분 우선 참고.'),
    '수주상황': ('', '"매출 및 수주상황" 부분 우선 참고.'),
    '지배구조': ('이사회,주주에 관한 사항,대주주', ''),
    '경영진/지배구조': ('이사회,주주에 관한 사항,대주주', ''),
}

# 더 쓰지 않기로 한 기업분석 프롬프트
DROP = ['매장점포', '원자재공급망', '보유자산']

# "첨부된 사업보고서를 우선으로 분석해줘." / "첨부된 사업/분기보고서를 …"
ATTACH_RE = re.compile(r'^첨부된 [^\n]*보고서를 우선으로 분석해줘\.[ \t]*$', re.M)

# 사업보고서 절이 아예 없는 프롬프트(경쟁력)에 끼워 넣을 자리
OUTPUT_RE = re.compile(r'^## 출력 형식[ \t]*$', re.M)


def _lf(text):
    """
    프롬프트는 화면의 textarea 에서 저장돼 줄끝이 CRLF 다. 그대로 두면
    '$' 앞에 \\r 이 남아 줄 단위 정규식이 하나도 안 맞는다 — 조용히
    아무것도 안 바꾸고 지나간다. 맞추기 전에 LF 로 눕힌다.
    """
    return (text or '').replace('\r\n', '\n')

def _variable(spec):
    return '{사업보고서:' + spec + '}' if spec else '{사업보고서}'


def _new_block(var, hint):
    lines = ['## 사업보고서', var, '', '위 사업보고서를 우선으로 분석해줘.']
    if hint:
        lines.append(hint)
    lines += ['보고서에 없는 내용만 검색으로 보완해줘.', '', '---', '', '']
    return '\n'.join(lines)


def apply(apps, schema_editor):
    ResearchPrompt = apps.get_model('stocks', 'ResearchPrompt')
    StockQuestionReport = apps.get_model('stocks', 'StockQuestionReport')

    changed, skipped = [], []
    for prompt in ResearchPrompt.objects.all():
        if prompt.question not in SECTION_SPEC:
            continue
        text = _lf(prompt.prompt)
        if '{사업보고서' in text:
            skipped.append(f'{prompt.question}: 이미 되어 있음')
            continue

        sections, hint = SECTION_SPEC[prompt.question]
        var = _variable(sections)
        if ATTACH_RE.search(text):
            # 있는 절의 "첨부된 …" 한 줄만 갈아끼운다. 수주잔고의
            # '"매출 및 수주상황" 부분 우선 참고.' 같은 줄은 그대로 둔다.
            new = ATTACH_RE.sub(var + '\n\n위 사업보고서를 우선으로 분석해줘.', text, count=1)
            how = '기존 절 교체'
        elif OUTPUT_RE.search(text):
            block = _new_block(var, hint)
            new = OUTPUT_RE.sub(lambda m: block + m.group(0), text, count=1)
            how = '새 절 삽입'
        else:
            skipped.append(f'{prompt.question}: 붙일 자리를 못 찾음 — 손으로 넣어야 함')
            continue

        prompt.prompt = new
        prompt.save(update_fields=['prompt'])
        changed.append(f'{prompt.question}: {how} ({var})')

    print()
    print(f'  기업분석 프롬프트 {len(changed)}개에 {{사업보고서}} 를 넣었습니다.')
    for line in changed:
        print(f'    ✓ {line}')
    for line in skipped:
        print(f'    · {line}')

    dropped = ResearchPrompt.objects.filter(question__in=DROP)
    names = list(dropped.values_list('question', flat=True))
    dropped.delete()
    if names:
        print(f'  더 쓰지 않는 프롬프트 삭제: {" · ".join(names)}')
    # 저장된 리서치 내용은 건드리지 않는다. 지우는 것은 되돌릴 수 없다.
    left = StockQuestionReport.objects.filter(question__in=DROP).count()
    if left:
        print(f'  (저장된 {DROP} 리서치 {left}건은 그대로 뒀습니다 — 일반 질문으로 남습니다)')


def undo(apps, schema_editor):
    """
    되돌리지 않는다.

    한 번 해봤다가 프롬프트를 망가뜨렸다. 절을 통째로 새로 넣은 것과 한 줄만
    갈아끼운 것을 나중에 구별할 방법이 없어서, 되돌린다면서 넣은 줄 일부만
    지우고 나머지를 남긴다. 프롬프트는 화면에서 고칠 수 있으니 어설픈
    자동 복구보다 그냥 두는 편이 낫다.
    """
    print()
    print('  0146 은 되돌리지 않습니다 — 프롬프트는 설정 화면에서 고치세요.')


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0145_drop_supply_prompt'),
    ]

    operations = [
        migrations.RunPython(apply, undo),
    ]
