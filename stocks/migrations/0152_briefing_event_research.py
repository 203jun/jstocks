# -*- coding: utf-8 -*-
"""
핵심브리핑과 이벤트를 기업분석 리서치 칸으로 내린다.

둘 다 종목 화면에 따로 자리를 갖고 있었다. 핵심브리핑은 Info 에 붙은
텍스트 칸이었고(관심종목 47개 중 30개, 마지막 갱신 2026-04-20), 이벤트는
날짜가 붙은 행 목록이었다(StockEvent 4건).

하는 일은 다른 리서치와 같다 — 프롬프트를 복사하고, AI 답변을 붙여넣고,
마크다운으로 읽는다. 자리만 달랐다.

핵심브리핑 프롬프트는 설정(prompt_briefing)에 있던 것을 그대로 가져오되
리서치가 알아듣는 이름으로 바꾼다.

    {밸류에이션분석}  ->  {기업분석: 밸류에이션}
    {업황매크로분석}  ->  {기업분석: 업황/매크로}
    {이벤트분석}      ->  {기업분석: 이벤트}
    {경쟁사분석}      ->  {기업분석: 경쟁사}

네 개가 사실은 리서치 결과였다. 리서치 칸으로 내려오니 이름으로 그냥
끌어올 수 있게 됐다 — 따로 만들어 두었던 briefingData 가 필요 없다.

{노다지}·{리포트요약} 은 더 이상 모으지 않는 자료라 그 절을 걷어낸다.
"""
import re

from django.db import migrations

def _rename(event_name):
    # 이벤트 칸 이름은 상용·로컬이 갈린다('이벤트' / '향후 이벤트').
    # 브리핑이 가리키는 이름을 실제 칸 이름에 맞춰야 값이 채워진다.
    return [
        ('{밸류에이션분석}', '{기업분석: 밸류에이션}'),
        ('{업황매크로분석}', '{기업분석: 업황/매크로}'),
        ('{이벤트분석}', '{기업분석: %s}' % event_name),
        ('{경쟁사분석}', '{기업분석: 경쟁사}'),
    ]

# '[제목]\n{변수}\n※ …' 세 줄이 한 덩어리다. 죽은 자료는 덩어리째 걷는다.
DEAD_BLOCK = r'\[(?:노다지|리포트)[^\]]*\]\r?\n[^\r\n]*\r?\n※[^\r\n]*\r?\n?'

EVENT_PROMPT = """너는 실전 주식 투자 전문가야.
{종목명} 투자자 입장에서 앞으로 무엇이 예정돼 있는지 정리해줘.

---

## 사전 검색
아래를 검색해서 확인해줘:
1. {종목명} 실적발표 예정일
2. {종목명} 예정된 공시·주주총회·배당 일정
3. {종목명} 신제품·수주·계약 발표 예정
4. {종목명} 속한 산업의 예정된 행사·정책 일정
5. {종목명} 락업 해제·전환사채 청구 가능 시점

---

## 종목 상황
- 현재가: {현재가} ({변동률}%)
- 52주 위치: {52주위치}
- 최근 공시·실적: {기업분석: 핵심브리핑}

---

## 출력 형식
확인된 일정만 적어라. 추측한 날짜는 적지 마라.
날짜가 확정이 아니면 "예정" 또는 "미정"으로 표시해라.

**향후 이벤트**

| 시기 | 이벤트 | 호재/악재/중립 | 영향 강도 | 출처 | 체크포인트 |

- 시기는 정확한 날짜가 있으면 날짜로, 없으면 "26년 2분기" 식으로
- 가까운 것부터
- 이미 지난 일정은 빼라

**가장 큰 것 하나**
- 앞으로 3개월 안에 주가를 가장 크게 움직일 이벤트 1개
- 그것이 호재로 작동할 조건과 악재로 작동할 조건
- 그 전에 확인해야 할 것

출력 시 중요 수치는 볼드 처리.
==중요 키워드/핵심 문구/결정적 수치는 ==내용== 형태로 하이라이트 처리==
LaTeX 서식 절대 사용 금지.
"""


def apply(apps, schema_editor):
    ResearchPrompt = apps.get_model('stocks', 'ResearchPrompt')
    SystemSetting = apps.get_model('stocks', 'SystemSetting')

    existing = set(ResearchPrompt.objects.values_list('question', flat=True))
    first = (ResearchPrompt.objects.order_by('order')
             .values_list('order', flat=True).first() or 1)
    print()

    # ── 이벤트 ──
    # 옛 이름('향후 이벤트')이 있으면 그것이 같은 칸이다. 새로 만들면 저장해
    # 둔 리서치가 갈 곳을 잃는다. 브리핑이 이 이름을 가리키므로 먼저 정한다.
    event_name = next((q for q in ('이벤트', '향후 이벤트') if q in existing), None)
    if event_name:
        print(f'  이벤트: 이미 있음 ("{event_name}")')
    else:
        event_name = '이벤트'
        ResearchPrompt.objects.create(
            question=event_name, prompt=EVENT_PROMPT, order=first - 1, needs_attachment=False)
        print('  이벤트: 만들었습니다')

    # ── 핵심브리핑 ──
    if '핵심브리핑' in existing:
        print('  핵심브리핑: 이미 있음')
    else:
        row = SystemSetting.objects.filter(key='prompt_briefing').first()
        text = (row.value if row else '') or ''
        if not text:
            print('  핵심브리핑: 설정에 프롬프트가 없어 빈 칸으로 만듭니다')
        for old, new in _rename(event_name):
            text = text.replace(old, new)
        text = re.sub(DEAD_BLOCK, '', text)
        # 두 자료가 다 빠지면 '직접 수집 자료' 절이 껍데기만 남는다
        text = re.sub(r'## 직접 수집 자료\r?\n(?:###[^\r\n]*\r?\n)?\s*(?=---)', '', text)
        text = re.sub(r'\n{4,}', '\n\n\n', text)
        ResearchPrompt.objects.create(
            question='핵심브리핑', prompt=text, order=first - 2, needs_attachment=False)
        print(f'  핵심브리핑: 만들었습니다 ({len(text):,}자)')


def undo(apps, schema_editor):
    ResearchPrompt = apps.get_model('stocks', 'ResearchPrompt')
    ResearchPrompt.objects.filter(question__in=['핵심브리핑', '이벤트']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0151_research_markdown_default'),
    ]

    operations = [
        migrations.RunPython(apply, undo),
    ]
