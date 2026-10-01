"""로그인 없이 보는 공유 페이지.

동료와 같이 보는 자리다. 그래서 두 가지를 지킨다.

  - 읽기만 한다. POST 경로를 두지 않는다.
  - 보유는 드러내지 않는다. 무엇을 들고 있는지는 내 사정이고,
    표에 필요한 값도 아니다 (build_status_rows 에 빈 집합을 준다).

표를 만드는 일은 stocks.status_table 한 곳에 있다. 종목 화면의 현황 표와
같은 함수를 쓰므로 한쪽만 고쳐져 어긋나는 일이 없다.
"""
from django.shortcuts import render

from stocks.models import Info
from stocks.status_table import build_status_rows

LEVEL = 'shared'


def index(request):
    """공유 종목 현황"""
    stocks = list(
        Info.objects.filter(is_active=True, interest_level=LEVEL)
        .prefetch_related('themes__category')
        .order_by('name')
    )
    # 보유 표시 없음 — 두 번째 인자가 빈 집합이면 level 은 'shared' 로 남는다
    status_stocks = build_status_rows(stocks, set(), include_etf=False)

    return render(request, 'ontoo/index.html', {
        'status_stocks': status_stocks,
    })
