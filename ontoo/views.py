"""로그인 없이 보는 공유 페이지.

동료와 같이 보는 자리다. 그래서 두 가지를 지킨다.

  - 읽기만 한다. POST 경로를 두지 않는다.
  - 보유는 드러내지 않는다. 무엇을 들고 있는지는 내 사정이고,
    표에 필요한 값도 아니다 (build_status_rows 에 빈 집합을 준다).

표와 프롬프트 본문을 만드는 일은 stocks.status_table 한 곳에 있다. 종목
화면과 같은 함수를 쓰므로 한쪽만 고쳐져 어긋나는 일이 없다.
"""
from django.shortcuts import render

from stocks.models import Info, SystemSetting
from stocks.status_table import build_status_rows, status_block_text

PROMPT_KEY = 'prompt_status'


def index(request):
    """공유 종목 현황"""
    stocks = list(
        Info.objects.filter(is_active=True, is_shared=True)
        .prefetch_related('themes__category')
        .order_by('name')
    )
    # 보유 표시 없음 — 두 번째 인자가 빈 집합이면 보유 여부가 새지 않는다
    status_stocks = build_status_rows(stocks, set(), include_etf=False)

    # 프롬프트는 복사만 한다. 고치는 길(⚙)도, 본문을 띄우는 창도 두지 않는다 —
    # 여기서 고치면 내 종목 화면의 프롬프트까지 같이 바뀐다.
    prompt_template = SystemSetting.objects.filter(
        key=PROMPT_KEY).values_list('value', flat=True).first() or ''
    status_data = '\n\n---\n\n'.join(status_block_text(i) for i in status_stocks)

    return render(request, 'ontoo/index.html', {
        'status_stocks': status_stocks,
        # 둘 다 있어야 복사가 뜻이 있다. 하나라도 없으면 버튼을 그리지 않는다.
        'can_copy_prompt': bool(prompt_template and status_data),
        'prompt_template': prompt_template,
        'status_data': status_data,
    })
