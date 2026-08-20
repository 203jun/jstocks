# -*- coding: utf-8 -*-
"""
파이프라인·R&D 프롬프트에도 사업보고서를 붙인다.

0146 에서 다섯 개만 하고 이 둘은 뺐다. 검색만으로 쓰는 프롬프트로 봤기
때문인데, 실제 보고서를 재보니 아니었다.

  II. 사업의 내용 > 6. 주요계약 및 연구개발활동 > 나. 연구개발활동
  8개 종목 중 7개에 있다. 3개년 연구개발비, 매출 대비 비율, 연구원 수까지
  표로 들어 있다 (이오테크닉스 22,742/22,441/20,625 백만원 · 6.5/7.7/7.3%,
  쎄트렉아이 연구원 98명).

바이오는 여기에 파이프라인이 통째로 들어 있다. 리가켐바이오 사업보고서에는
후보물질 코드(LCB14·71·73·84·97), 모달리티(HER2/ROR1/CD19/TROP2/L1CAM-ADC),
임상 단계, 기술이전 상대(Fosun·CStone·익수다·얀센·오노), 계약금액까지 있다.
검색으로는 이만큼 정확히 못 모은다.

'XI. 그 밖에 투자자 보호를 위하여 필요한 사항' 도 봤지만 1,273자에 임상
언급이 0회였다. II. 사업의 내용 하나면 된다.

붙이는 자리가 0146 과 다르다. 이 둘은 '## 사업보고서' 절이 아예 없고
'## 사전 검색' 이 먼저 온다. 출력 형식 앞에 넣으면 검색 뒤로 밀려서
"보고서에 없는 내용만 검색으로 보완해줘" 와 순서가 뒤집힌다.
"""
import re

from django.db import migrations

HINT = '"주요계약 및 연구개발활동" 부분 우선 참고.'

# 프롬프트 이름은 대소문자가 갈린다(R&D / r&d). 소문자로 맞춰 견준다.
QUESTIONS = {'파이프라인', 'r&d'}

# 사업보고서 절을 끼워 넣을 자리. 앞엣것부터 찾는다 — 검색보다 앞이라야
# "보고서에 없는 내용만 검색으로" 가 말이 된다.
ANCHORS = [
    ('## 사전 검색', re.compile(r'^## 사전 검색[ \t]*$', re.M)),
    ('## 출력 형식', re.compile(r'^## 출력 형식[ \t]*$', re.M)),
]

BLOCK = f"""## 사업보고서
{{사업보고서}}

위 사업보고서를 우선으로 분석해줘.
{HINT}
보고서에 없는 내용만 검색으로 보완해줘.

---

"""


def _lf(text):
    """textarea 에서 저장돼 줄끝이 CRLF 다. 줄 단위 정규식이 맞으려면 눕혀야 한다."""
    return (text or '').replace('\r\n', '\n')


def apply(apps, schema_editor):
    ResearchPrompt = apps.get_model('stocks', 'ResearchPrompt')

    changed, skipped = [], []
    for prompt in ResearchPrompt.objects.all():
        if prompt.question.lower() not in QUESTIONS:
            continue
        text = _lf(prompt.prompt)
        if '{사업보고서' in text:
            skipped.append(f'{prompt.question}: 이미 되어 있음')
            continue

        for label, anchor in ANCHORS:
            if anchor.search(text):
                prompt.prompt = anchor.sub(lambda m: BLOCK + m.group(0), text, count=1)
                prompt.save(update_fields=['prompt'])
                changed.append(f'{prompt.question}: {label} 앞에 삽입')
                break
        else:
            skipped.append(f'{prompt.question}: 붙일 자리를 못 찾음 — 손으로 넣어야 함')

    print()
    print(f'  파이프라인·R&D 프롬프트 {len(changed)}개에 {{사업보고서}} 를 넣었습니다.')
    for line in changed:
        print(f'    ✓ {line}')
    for line in skipped:
        print(f'    · {line}')
    if not changed and not skipped:
        print('    · 대상 프롬프트가 없습니다 (파이프라인 · R&D)')


def undo(apps, schema_editor):
    """0146 과 같은 이유로 되돌리지 않는다 — 프롬프트는 화면에서 고칠 수 있다."""
    print()
    print('  0147 은 되돌리지 않습니다 — 프롬프트는 설정 화면에서 고치세요.')


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0146_business_report_variable'),
    ]

    operations = [
        migrations.RunPython(apply, undo),
    ]
