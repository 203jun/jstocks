import json
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from decouple import config
from telethon import TelegramClient
from .models import Info, Financial, DailyChart, WeeklyChart, MonthlyChart, Report


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

    # 일봉 차트 데이터 (최근 240일 + 이평선 계산용 60일 = 300일)
    daily_charts = list(DailyChart.objects.filter(
        stock=stock
    ).order_by('-date')[:300])
    daily_charts.reverse()

    # 이평선 계산 (20일, 60일)
    def calc_ma(data, period):
        result = []
        for i in range(len(data)):
            if i < period - 1:
                result.append(None)
            else:
                avg = sum(d.closing_price for d in data[i - period + 1:i + 1]) / period
                result.append(round(avg))
        return result

    ma20 = calc_ma(daily_charts, 20)
    ma60 = calc_ma(daily_charts, 60)

    # 최근 240일만 사용
    daily_charts = daily_charts[-240:]
    ma20 = ma20[-240:]
    ma60 = ma60[-240:]

    daily_candle_data = [
        {
            'time': d.date.strftime('%Y-%m-%d'),
            'open': d.opening_price,
            'high': d.high_price,
            'low': d.low_price,
            'close': d.closing_price,
        }
        for d in daily_charts
    ]
    daily_volume_data = [
        {
            'time': d.date.strftime('%Y-%m-%d'),
            'value': d.trading_volume,
            'color': '#ef5350' if d.closing_price >= d.opening_price else '#26a69a',
        }
        for d in daily_charts
    ]
    daily_ma20_data = [
        {'time': daily_charts[i].date.strftime('%Y-%m-%d'), 'value': ma20[i]}
        for i in range(len(daily_charts)) if ma20[i] is not None
    ]
    daily_ma60_data = [
        {'time': daily_charts[i].date.strftime('%Y-%m-%d'), 'value': ma60[i]}
        for i in range(len(daily_charts)) if ma60[i] is not None
    ]

    # 주봉 차트 데이터 (최근 104주 = 2년)
    weekly_charts = list(WeeklyChart.objects.filter(
        stock=stock
    ).order_by('-date')[:104])
    weekly_charts.reverse()

    weekly_candle_data = [
        {
            'time': w.date.strftime('%Y-%m-%d'),
            'open': w.opening_price,
            'high': w.high_price,
            'low': w.low_price,
            'close': w.closing_price,
        }
        for w in weekly_charts
    ]
    weekly_volume_data = [
        {
            'time': w.date.strftime('%Y-%m-%d'),
            'value': w.trading_volume,
            'color': '#ef5350' if w.closing_price >= w.opening_price else '#26a69a',
        }
        for w in weekly_charts
    ]

    # 월봉 차트 데이터 (최근 72개월 = 6년)
    monthly_charts = list(MonthlyChart.objects.filter(
        stock=stock
    ).order_by('-date')[:72])
    monthly_charts.reverse()

    monthly_candle_data = [
        {
            'time': m.date.strftime('%Y-%m-%d'),
            'open': m.opening_price,
            'high': m.high_price,
            'low': m.low_price,
            'close': m.closing_price,
        }
        for m in monthly_charts
    ]
    monthly_volume_data = [
        {
            'time': m.date.strftime('%Y-%m-%d'),
            'value': m.trading_volume,
            'color': '#ef5350' if m.closing_price >= m.opening_price else '#26a69a',
        }
        for m in monthly_charts
    ]

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
        'daily_candle_data': json.dumps(daily_candle_data),
        'daily_volume_data': json.dumps(daily_volume_data),
        'daily_ma20_data': json.dumps(daily_ma20_data),
        'daily_ma60_data': json.dumps(daily_ma60_data),
        'weekly_candle_data': json.dumps(weekly_candle_data),
        'weekly_volume_data': json.dumps(weekly_volume_data),
        'monthly_candle_data': json.dumps(monthly_candle_data),
        'monthly_volume_data': json.dumps(monthly_volume_data),
    }
    return render(request, 'stocks/stock_detail.html', context)


def stock_edit(request, code):
    """종목 편집 페이지"""
    stock = get_object_or_404(Info, code=code)

    if request.method == 'POST':
        interest_level = request.POST.get('interest_level', '')
        stock.interest_level = interest_level if interest_level else None
        stock.save()
        messages.success(request, f'{stock.name} 정보가 저장되었습니다.')
        return redirect('stocks:stock_detail', code=code)

    # 관심 단계 선택지
    interest_choices = Info._meta.get_field('interest_level').choices

    # 리포트 (최근 20개)
    reports = list(Report.objects.filter(stock=stock).order_by('-date')[:20])

    # 목표가 차트 데이터 (리포트 날짜 범위의 주가 + 목표가)
    if reports:
        # 리포트 날짜 범위
        report_dates = [r.date for r in reports]
        min_date = min(report_dates)

        # 해당 기간의 일봉 데이터
        daily_prices = list(DailyChart.objects.filter(
            stock=stock,
            date__gte=min_date
        ).order_by('date').values('date', 'closing_price'))

        # 날짜별 종가 딕셔너리
        price_by_date = {d['date']: d['closing_price'] for d in daily_prices}

        # 차트 데이터 생성
        price_chart_data = [
            {'x': d['date'].strftime('%Y-%m-%d'), 'y': d['closing_price']}
            for d in daily_prices
        ]

        # 목표가 데이터 (같은 날 여러 개면 평균)
        target_by_date = defaultdict(list)
        for r in reports:
            if r.target_price:
                target_by_date[r.date].append(r.target_price)

        target_chart_data = [
            {'x': date.strftime('%Y-%m-%d'), 'y': round(sum(prices) / len(prices))}
            for date, prices in sorted(target_by_date.items())
        ]

        # 리포트별 괴리율 계산 (목표가 / 종가 - 1) * 100
        for r in reports:
            if r.target_price and r.date in price_by_date:
                closing = price_by_date[r.date]
                r.gap_rate = round((r.target_price / closing - 1) * 100, 1)
            else:
                r.gap_rate = None

        # 괴리율 차트 데이터 (날짜별 평균 목표가 기준)
        gap_chart_data = []
        for date, prices in sorted(target_by_date.items()):
            if date in price_by_date:
                avg_target = round(sum(prices) / len(prices))
                closing = price_by_date[date]
                gap = round((avg_target / closing - 1) * 100, 1)
                gap_chart_data.append({'x': date.strftime('%Y-%m-%d'), 'y': gap})
    else:
        price_chart_data = []
        target_chart_data = []
        gap_chart_data = []

    context = {
        'stock': stock,
        'interest_choices': interest_choices,
        'reports': reports,
        'price_chart_data': json.dumps(price_chart_data),
        'target_chart_data': json.dumps(target_chart_data),
        'gap_chart_data': json.dumps(gap_chart_data),
    }
    return render(request, 'stocks/stock_edit.html', context)


# 텔레그램 채널 목록 (채널ID: 표시명)
TELEGRAM_CHANNELS = {
    '@darthacking': '주식공시',
    '@valjuman': 'GL리서치',
    '@gaoshoukorea': '재야의고수',
    '@FastStockNews': '급등일보',
    '@companyreport': '증권사리포트',
    '@one_going': '요약고잉',
    '@Brain_And_Body_Research': 'Brain',
    '@athletes_village': '선수촌',
    '@investment_puzzle': '퍼즐한조각',
    '@kimcharger': '김철저',
    '@YeouidoStory2': '여의도스토리',
    '@bumgore': '제이슨',
    '@ym_research': 'YM리서치',
    '@Yeouido_Lab': '여의도톹아보기',
    '@Ten_level': '텐렙',
    '@realtime_stock_news': '실시간뉴스',
    '@corevalue': '가치투자클럽',
    '@hedgehara': 'Pluto',
    '@maddingStock': '스탁이지',
    '@Desperatestudycafe': '간절한',
    '@moneythemestock': '미니서퍼',
    '@theelec': '디일렉',
    '@KiwoomResearch': '키움리서치',
    '@quick_report': 'AI리포트',
    '@jeilstock': '이지스',
    '@butler_works': '버틀러리포트',
    '@pharmbiohana': '원리버',
}


@require_GET
def search_telegram(request):
    """텔레그램 채널 검색 API"""
    keyword = request.GET.get('keyword', '')
    limit = int(request.GET.get('limit', 30))
    days = int(request.GET.get('days', 7))  # 기본 7일, 최대 180일

    if not keyword:
        return JsonResponse({'error': '검색어가 필요합니다.'}, status=400)

    api_id = config('TELEGRAM_API_ID')
    api_hash = config('TELEGRAM_API_HASH')

    async def search():
        async with TelegramClient('telegram_session', api_id, api_hash) as client:
            # 지정된 기간 전 날짜
            date_limit = datetime.now(timezone.utc) - timedelta(days=min(days, 180))

            # 채널별 결과
            by_channel = {}

            for channel in TELEGRAM_CHANNELS.keys():
                try:
                    entity = await client.get_entity(channel)
                    msgs = await client.get_messages(entity, search=keyword, limit=limit)

                    channel_msgs = [m for m in msgs if m.text]

                    # 기간 이내 메시지 필터링
                    recent_msgs = [m for m in channel_msgs if m.date >= date_limit]

                    # 3개 미만이면 날짜 상관없이 최대 3개
                    if len(recent_msgs) < 3:
                        recent_msgs = channel_msgs[:3]

                    # 날짜별 그룹핑
                    by_date = defaultdict(list)
                    for msg in recent_msgs:
                        date_str = msg.date.strftime('%Y-%m-%d')
                        by_date[date_str].append({
                            'time': msg.date.strftime('%H:%M'),
                            'text': msg.text
                        })

                    by_channel[channel] = dict(by_date)
                except Exception:
                    by_channel[channel] = {}  # 채널 접근 실패

            return by_channel

    try:
        results = asyncio.run(search())
        return JsonResponse({
            'success': True,
            'keyword': keyword,
            'channel_names': TELEGRAM_CHANNELS,
            'results': results
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_GET
def search_report(request):
    """애널리스트 리포트 검색 API (FnGuide)"""
    import requests as http_requests

    code = request.GET.get('code', '')
    count = int(request.GET.get('count', 20))

    if not code:
        return JsonResponse({'error': '종목코드가 필요합니다.'}, status=400)

    url = 'https://comp.wisereport.co.kr/company/ajax/c1080001_data.aspx'
    params = {
        'cmp_cd': code,
        'cnt': count,
        'page': 1,
    }
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': f'https://comp.wisereport.co.kr/company/c1080001.aspx?cmp_cd={code}',
    }

    try:
        response = http_requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        reports = data.get('lists', [])

        return JsonResponse({
            'success': True,
            'code': code,
            'reports': reports
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_GET
def search_nodaji(request):
    """노다지(네이버 프리미엄 콘텐츠) 검색 API - Playwright 사용"""
    from playwright.sync_api import sync_playwright

    keyword = request.GET.get('keyword', '')

    if not keyword:
        return JsonResponse({'error': '검색어가 필요합니다.'}, status=400)

    url = f'https://contents.premium.naver.com/ystreet/irnote/search?searchQuery={keyword}'

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until='networkidle')

            # 페이지 로드 대기 및 스크롤
            page.wait_for_timeout(3000)
            page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            page.wait_for_timeout(2000)

            # 디버그: HTML 구조 확인
            html = page.content()
            browser.close()

            # HTML에서 검색 결과 파싱
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')

            results = []
            # 노다지 검색 결과 셀렉터
            cards = soup.select('.psp_content_item')

            for card in cards[:20]:
                # 실제 기사 제목 (.psp_name)
                title_el = card.select_one('strong.psp_name')
                title = title_el.get_text(strip=True) if title_el else ''

                # 카테고리
                category_el = card.select_one('.psp_category_name')
                category = category_el.get_text(strip=True) if category_el else ''

                # 날짜
                date_el = card.select_one('.psp_content_info_text')
                date = date_el.get_text(strip=True) if date_el else ''

                # 링크
                link_el = card.select_one('a.psp_content_link')
                link = ''
                if link_el and link_el.get('href'):
                    link = link_el.get('href')
                    if not link.startswith('http'):
                        link = 'https://contents.premium.naver.com' + link

                if title:
                    results.append({
                        'title': title,
                        'category': category,
                        'date': date,
                        'link': link,
                    })

        return JsonResponse({
            'success': True,
            'keyword': keyword,
            'results': results,
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_GET
def search_disclosure(request):
    """공시 검색 API (darthacking 채널만, 2주)"""
    keyword = request.GET.get('keyword', '')
    limit = int(request.GET.get('limit', 50))

    if not keyword:
        return JsonResponse({'error': '검색어가 필요합니다.'}, status=400)

    api_id = config('TELEGRAM_API_ID')
    api_hash = config('TELEGRAM_API_HASH')

    async def search():
        async with TelegramClient('telegram_session', api_id, api_hash) as client:
            # 2주 전 날짜
            two_weeks_ago = datetime.now(timezone.utc) - timedelta(days=14)

            try:
                entity = await client.get_entity('@darthacking')
                msgs = await client.get_messages(entity, search=keyword, limit=limit)

                channel_msgs = [m for m in msgs if m.text]

                # 2주 이내 메시지 필터링
                recent_msgs = [m for m in channel_msgs if m.date >= two_weeks_ago]

                # 날짜별 그룹핑
                by_date = defaultdict(list)
                for msg in recent_msgs:
                    date_str = msg.date.strftime('%Y-%m-%d')
                    by_date[date_str].append({
                        'time': msg.date.strftime('%H:%M'),
                        'text': msg.text
                    })

                return dict(by_date)
            except Exception:
                return {}

    try:
        results = asyncio.run(search())
        return JsonResponse({
            'success': True,
            'keyword': keyword,
            'results': results
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
