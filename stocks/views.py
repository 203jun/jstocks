import json
from django.shortcuts import render, get_object_or_404
from .models import Info, Financial


def index(request):
    """메인 페이지 (대시보드)"""
    return render(request, 'stocks/index.html')


def stock_list(request):
    """종목 리스트 페이지"""
    # 검색어
    query = request.GET.get('q', '')
    # 시장 필터
    market = request.GET.get('market', '')
    # 정렬
    sort = request.GET.get('sort', '-market_cap')

    stocks = Info.objects.filter(is_active=True).exclude(market='ETF')

    if query:
        stocks = stocks.filter(name__icontains=query) | stocks.filter(code__icontains=query)

    if market:
        stocks = stocks.filter(market=market)

    stocks = stocks.order_by(sort)[:100]  # 상위 100개만

    context = {
        'stocks': stocks,
        'query': query,
        'market': market,
        'sort': sort,
    }
    return render(request, 'stocks/stock_list.html', context)


def stock_detail(request, code):
    """종목 상세 페이지"""
    stock = get_object_or_404(Info, code=code)

    # 연간 재무 데이터 (최근 6년)
    annual_financials = list(Financial.objects.filter(
        stock=stock,
        quarter__isnull=True
    ).order_by('-year')[:6])
    annual_financials.reverse()

    # 분기 재무 데이터 (최근 25분기)
    quarterly_financials = list(Financial.objects.filter(
        stock=stock,
        quarter__isnull=False
    ).order_by('-year', '-quarter')[:25])
    quarterly_financials.reverse()

    # 연간 차트 데이터
    annual_labels = [str(f.year) for f in annual_financials]
    annual_revenue = [int(f.revenue / 100000000) if f.revenue else 0 for f in annual_financials]
    annual_op = [int(f.operating_profit / 100000000) if f.operating_profit else 0 for f in annual_financials]
    annual_estimated = [f.is_estimated for f in annual_financials]

    # 분기 차트 데이터
    quarterly_labels = [f"{f.year} {f.quarter}" for f in quarterly_financials]
    quarterly_revenue = [int(f.revenue / 100000000) if f.revenue else 0 for f in quarterly_financials]
    quarterly_op = [int(f.operating_profit / 100000000) if f.operating_profit else 0 for f in quarterly_financials]
    quarterly_estimated = [f.is_estimated for f in quarterly_financials]

    context = {
        'stock': stock,
        'annual_labels': json.dumps(annual_labels),
        'annual_revenue': json.dumps(annual_revenue),
        'annual_op': json.dumps(annual_op),
        'annual_estimated': json.dumps(annual_estimated),
        'quarterly_labels': json.dumps(quarterly_labels),
        'quarterly_revenue': json.dumps(quarterly_revenue),
        'quarterly_op': json.dumps(quarterly_op),
        'quarterly_estimated': json.dumps(quarterly_estimated),
    }
    return render(request, 'stocks/stock_detail.html', context)
