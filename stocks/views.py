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
from django.views.decorators.http import require_POST
from .models import Info, Financial, DailyChart, WeeklyChart, MonthlyChart, Report, Nodaji, Gongsi, Schedule, IndexChart, MarketTrend, InvestorTrend, ShortSelling


def index(request):
    """종목 대시보드 (관심종목)"""
    super_stocks = Info.objects.filter(interest_level='super', is_active=True).order_by('-market_cap')
    normal_stocks = Info.objects.filter(interest_level='normal', is_active=True).order_by('-market_cap')
    incubator_stocks = Info.objects.filter(interest_level='incubator', is_active=True).order_by('-market_cap')

    context = {
        'super_stocks': super_stocks,
        'normal_stocks': normal_stocks,
        'incubator_stocks': incubator_stocks,
    }
    return render(request, 'stocks/index.html', context)


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

    # 일정
    schedules = Schedule.objects.filter(stock=stock).order_by('date_sort')

    # 섹터 (업종) - 고유한 이름만 추출
    sectors = stock.sectors.values('code', 'name').distinct().order_by('name')

    context = {
        'stock': stock,
        'schedules': schedules,
        'sectors': sectors,
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
        stock.investment_point = request.POST.get('investment_point', '')
        stock.risk = request.POST.get('risk', '')
        stock.save()
        messages.success(request, f'{stock.name} 정보가 저장되었습니다.')
        return redirect('stocks:stock_edit', code=code)

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

    # 노다지 기사 (종목명 포함된 것만, 최근 20개)
    nodaji_articles = Nodaji.objects.filter(
        stock=stock,
        title__contains=stock.name
    ).order_by('-date')[:20]

    # 공시 (최근 20개)
    gongsi_list = Gongsi.objects.filter(stock=stock).order_by('-date')[:20]

    # 일정
    schedules = Schedule.objects.filter(stock=stock).order_by('date_sort')

    # 수급 (투자자별 매매동향, 최근 60일)
    investor_trends = list(InvestorTrend.objects.filter(stock=stock).order_by('-date')[:60])

    # 수급 누적 차트 데이터 (오래된 날짜부터)
    investor_chart_data = []
    if investor_trends:
        trends_asc = list(reversed(investor_trends))
        cum_individual = 0
        cum_foreign = 0
        cum_institution = 0
        for t in trends_asc:
            cum_individual += t.individual or 0
            cum_foreign += t.foreign or 0
            cum_institution += t.institution or 0
            investor_chart_data.append({
                'date': t.date.strftime('%m.%d'),
                'individual': cum_individual,
                'foreign': cum_foreign,
                'institution': cum_institution,
            })

    # 공매도 (최근 60일)
    short_sellings = ShortSelling.objects.filter(stock=stock).order_by('-date')[:60]

    context = {
        'stock': stock,
        'interest_choices': interest_choices,
        'reports': reports,
        'price_chart_data': json.dumps(price_chart_data),
        'target_chart_data': json.dumps(target_chart_data),
        'gap_chart_data': json.dumps(gap_chart_data),
        'nodaji_articles': nodaji_articles,
        'gongsi_list': gongsi_list,
        'schedules': schedules,
        'investor_trends': investor_trends,
        'investor_chart_data': json.dumps(investor_chart_data),
        'short_sellings': short_sellings,
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
    keyword = request.GET.get('keyword', '')

    if not keyword:
        return JsonResponse({'error': '검색어가 필요합니다.'}, status=400)

    url = f'https://contents.premium.naver.com/ystreet/irnote/search?searchQuery={keyword}'

    try:
        from playwright.sync_api import sync_playwright
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


def market(request):
    """시황 페이지"""
    # KOSPI 차트 데이터 (최근 240일)
    kospi_charts = list(IndexChart.objects.filter(code='KOSPI').order_by('-date')[:240])
    kospi_charts.reverse()

    kospi_candle_data = [
        {
            'time': c.date.strftime('%Y-%m-%d'),
            'open': float(c.opening_price),
            'high': float(c.high_price),
            'low': float(c.low_price),
            'close': float(c.closing_price),
        }
        for c in kospi_charts
    ]
    kospi_volume_data = [
        {
            'time': c.date.strftime('%Y-%m-%d'),
            'value': c.trading_volume,
            'color': '#ef5350' if c.closing_price >= c.opening_price else '#26a69a',
        }
        for c in kospi_charts
    ]

    # KOSDAQ 차트 데이터 (최근 240일)
    kosdaq_charts = list(IndexChart.objects.filter(code='KOSDAQ').order_by('-date')[:240])
    kosdaq_charts.reverse()

    kosdaq_candle_data = [
        {
            'time': c.date.strftime('%Y-%m-%d'),
            'open': float(c.opening_price),
            'high': float(c.high_price),
            'low': float(c.low_price),
            'close': float(c.closing_price),
        }
        for c in kosdaq_charts
    ]
    kosdaq_volume_data = [
        {
            'time': c.date.strftime('%Y-%m-%d'),
            'value': c.trading_volume,
            'color': '#ef5350' if c.closing_price >= c.opening_price else '#26a69a',
        }
        for c in kosdaq_charts
    ]

    # 최신 데이터
    kospi_latest = kospi_charts[-1] if kospi_charts else None
    kosdaq_latest = kosdaq_charts[-1] if kosdaq_charts else None

    # 전일 대비
    if len(kospi_charts) >= 2:
        kospi_change = float(kospi_charts[-1].closing_price - kospi_charts[-2].closing_price)
        kospi_change_rate = round(kospi_change / float(kospi_charts[-2].closing_price) * 100, 2)
    else:
        kospi_change = 0
        kospi_change_rate = 0

    if len(kosdaq_charts) >= 2:
        kosdaq_change = float(kosdaq_charts[-1].closing_price - kosdaq_charts[-2].closing_price)
        kosdaq_change_rate = round(kosdaq_change / float(kosdaq_charts[-2].closing_price) * 100, 2)
    else:
        kosdaq_change = 0
        kosdaq_change_rate = 0

    # MarketTrend data (top 20 per market)
    kospi_trends = MarketTrend.objects.filter(market='KOSPI').order_by('-date')[:20]
    kosdaq_trends = MarketTrend.objects.filter(market='KOSDAQ').order_by('-date')[:20]
    futures_trends = MarketTrend.objects.filter(market='FUTURES').order_by('-date')[:20]

    # Cumulative chart data (120 days)
    def get_cumulative_data(market):
        trends = list(MarketTrend.objects.filter(market=market).order_by('-date')[:120])
        trends.reverse()  # oldest first

        cumulative_individual = 0
        cumulative_foreign = 0
        cumulative_institution = 0

        chart_data = []
        for t in trends:
            cumulative_individual += t.individual
            cumulative_foreign += t.foreign
            cumulative_institution += t.institution
            chart_data.append({
                'date': t.date.strftime('%Y-%m-%d'),
                'individual': cumulative_individual,
                'foreign': cumulative_foreign,
                'institution': cumulative_institution,
            })
        return chart_data

    kospi_cumulative = get_cumulative_data('KOSPI')
    kosdaq_cumulative = get_cumulative_data('KOSDAQ')
    futures_cumulative = get_cumulative_data('FUTURES')

    context = {
        'kospi_candle_data': json.dumps(kospi_candle_data),
        'kospi_volume_data': json.dumps(kospi_volume_data),
        'kosdaq_candle_data': json.dumps(kosdaq_candle_data),
        'kosdaq_volume_data': json.dumps(kosdaq_volume_data),
        'kospi_latest': kospi_latest,
        'kosdaq_latest': kosdaq_latest,
        'kospi_change': kospi_change,
        'kospi_change_rate': kospi_change_rate,
        'kosdaq_change': kosdaq_change,
        'kosdaq_change_rate': kosdaq_change_rate,
        'kospi_trends': kospi_trends,
        'kosdaq_trends': kosdaq_trends,
        'futures_trends': futures_trends,
        'kospi_cumulative': json.dumps(kospi_cumulative),
        'kosdaq_cumulative': json.dumps(kosdaq_cumulative),
        'futures_cumulative': json.dumps(futures_cumulative),
    }
    return render(request, 'stocks/market.html', context)


@require_GET
def fetch_nodaji_brief(request):
    """노다지 브리프 API (모닝브리프/마감브리프 최신 날짜만)"""
    try:
        from playwright.sync_api import sync_playwright
        from bs4 import BeautifulSoup
    except ImportError as e:
        return JsonResponse({'error': f'필수 모듈 없음: {e}'}, status=500)

    # 브리프 카테고리 페이지
    url = 'https://contents.premium.naver.com/ystreet/irnote/contents?categoryId=1949743df60000ube'

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until='networkidle')

            # 페이지 로드 대기
            page.wait_for_timeout(3000)
            page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            page.wait_for_timeout(2000)

            html = page.content()
            browser.close()

            # HTML 파싱
            soup = BeautifulSoup(html, 'html.parser')
            results = []
            items = soup.select('.content_item')

            for item in items:
                # 제목
                title_el = item.select_one('.content_title')
                title = title_el.get_text(strip=True) if title_el else ''

                # 모닝브리프, 마감브리프만 필터링
                if not title.startswith('[모닝브리프]') and not title.startswith('[마감브리프]'):
                    continue

                # 카테고리 추출
                category = '모닝브리프' if '[모닝브리프]' in title else '마감브리프'

                # 날짜 (두번째 info_text)
                info_texts = item.select('.content_info_text')
                date = info_texts[1].get_text(strip=True) if len(info_texts) > 1 else ''

                # 링크
                link_el = item.select_one('a.content_text_link')
                link = ''
                if link_el and link_el.get('href'):
                    link = link_el.get('href')
                    if not link.startswith('http'):
                        link = 'https://contents.premium.naver.com' + link

                if title:
                    results.append({
                        'category': category,
                        'title': title,
                        'date': date,
                        'link': link,
                    })

        # 모닝브리프, 마감브리프 각각 최신 1개씩
        morning = [r for r in results if r['category'] == '모닝브리프']
        evening = [r for r in results if r['category'] == '마감브리프']

        filtered = []
        if morning:
            filtered.append(morning[0])
        if evening:
            filtered.append(evening[0])

        return JsonResponse({
            'success': True,
            'results': filtered,
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def nodaji_summary(request, nodaji_id):
    """노다지 요약 편집 페이지"""
    nodaji = get_object_or_404(Nodaji, id=nodaji_id)

    if request.method == 'POST':
        summary = request.POST.get('summary', '')
        nodaji.summary = summary
        nodaji.save()
        messages.success(request, '요약이 저장되었습니다.')
        return redirect('stocks:nodaji_summary', nodaji_id=nodaji_id)

    return render(request, 'stocks/nodaji_summary.html', {
        'nodaji': nodaji,
    })


@require_GET
def fetch_dart(request, code):
    """DART 공시 조회 API"""
    try:
        from playwright.sync_api import sync_playwright
        from bs4 import BeautifulSoup
    except ImportError as e:
        return JsonResponse({'error': f'필수 모듈 없음: {e}'}, status=500)

    url = f'https://dart.fss.or.kr/html/search/SearchCompany_M2.html?textCrpNM={code}'

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until='domcontentloaded', timeout=60000)
            page.wait_for_timeout(5000)

            html = page.content()
            browser.close()

            soup = BeautifulSoup(html, 'html.parser')
            table = soup.select_one('table')
            rows = table.select('tbody tr') if table else []

            results = []
            for row in rows[:20]:
                cells = row.select('td')
                if len(cells) >= 5:
                    report_el = cells[2].select_one('a')
                    report_name = report_el.get_text(strip=True) if report_el else ''
                    report_link = report_el.get('href', '') if report_el else ''

                    if report_link and not report_link.startswith('http'):
                        report_link = 'https://dart.fss.or.kr' + report_link

                    results.append({
                        'date': cells[4].get_text(strip=True),
                        'title': report_name,
                        'link': report_link,
                        'submitter': cells[3].get_text(strip=True),
                    })

        return JsonResponse({
            'success': True,
            'results': results,
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_POST
def schedule_add(request, code):
    """일정 추가 API"""
    stock = get_object_or_404(Info, code=code)

    date_text = request.POST.get('date_text', '').strip()
    date_sort = request.POST.get('date_sort', '').strip()
    content = request.POST.get('content', '').strip()

    if not date_text or not content:
        return JsonResponse({'error': '날짜와 내용을 입력해주세요.'}, status=400)

    # date_sort 파싱
    date_sort_value = None
    if date_sort:
        try:
            date_sort_value = datetime.strptime(date_sort, '%Y-%m-%d').date()
        except ValueError:
            pass

    schedule = Schedule.objects.create(
        stock=stock,
        date_text=date_text,
        date_sort=date_sort_value,
        content=content,
    )

    return JsonResponse({
        'success': True,
        'id': schedule.id,
        'date_text': schedule.date_text,
        'date_sort': schedule.date_sort.strftime('%Y-%m-%d') if schedule.date_sort else '',
        'content': schedule.content,
    })


@require_POST
def schedule_delete(request, schedule_id):
    """일정 삭제 API"""
    schedule = get_object_or_404(Schedule, id=schedule_id)
    schedule.delete()

    return JsonResponse({'success': True})


def sector(request):
    """섹터 페이지"""
    from .models import Sector

    # === 업종 데이터 ===
    latest_kospi_date = Sector.objects.filter(market='KOSPI').order_by('-date').values_list('date', flat=True).first()
    latest_kosdaq_date = Sector.objects.filter(market='KOSDAQ').order_by('-date').values_list('date', flat=True).first()

    kospi_sectors = []
    if latest_kospi_date:
        kospi_sectors = list(Sector.objects.filter(
            market='KOSPI',
            date=latest_kospi_date
        ).order_by('-foreign_net_buying'))

    kosdaq_sectors = []
    if latest_kosdaq_date:
        kosdaq_sectors = list(Sector.objects.filter(
            market='KOSDAQ',
            date=latest_kosdaq_date
        ).order_by('-foreign_net_buying'))

    # 업종 60일 차트 데이터
    def get_sector_chart_data(market):
        dates = list(Sector.objects.filter(market=market)
                     .values_list('date', flat=True)
                     .distinct()
                     .order_by('-date')[:60])
        dates.reverse()

        if not dates:
            return {}

        sectors = Sector.objects.filter(market=market, date=dates[-1]).values_list('code', 'name')

        chart_data = {}
        for code, name in sectors:
            sector_data = list(Sector.objects.filter(
                market=market,
                code=code,
                date__in=dates
            ).order_by('date').values(
                'date', 'individual_net_buying', 'foreign_net_buying', 'institution_net_buying'
            ))

            cum_individual = 0
            cum_foreign = 0
            cum_institution = 0
            cumulative_data = []

            for d in sector_data:
                cum_individual += d['individual_net_buying'] or 0
                cum_foreign += d['foreign_net_buying'] or 0
                cum_institution += d['institution_net_buying'] or 0
                cumulative_data.append({
                    'date': d['date'].strftime('%m.%d'),
                    'individual': cum_individual,
                    'foreign': cum_foreign,
                    'institution': cum_institution,
                })

            chart_data[code] = {
                'name': name,
                'data': cumulative_data
            }

        return chart_data

    kospi_chart_data = get_sector_chart_data('KOSPI')
    kosdaq_chart_data = get_sector_chart_data('KOSDAQ')

    context = {
        'latest_kospi_date': latest_kospi_date,
        'latest_kosdaq_date': latest_kosdaq_date,
        'kospi_sectors': kospi_sectors,
        'kosdaq_sectors': kosdaq_sectors,
        'kospi_chart_data': json.dumps(kospi_chart_data),
        'kosdaq_chart_data': json.dumps(kosdaq_chart_data),
    }
    return render(request, 'stocks/sector.html', context)


@require_GET
def sector_date_data(request):
    """섹터 날짜별 데이터 API (차트용)"""
    from .models import Sector

    market = request.GET.get('market', 'KOSPI')
    code = request.GET.get('code', '')

    if not code:
        return JsonResponse({'error': '업종 코드가 필요합니다.'}, status=400)

    data = list(Sector.objects.filter(
        market=market,
        code=code
    ).order_by('-date')[:10].values(
        'date', 'name', 'individual_net_buying', 'foreign_net_buying', 'institution_net_buying'
    ))

    # 오래된 날짜부터 정렬 (차트용)
    data.reverse()

    # date를 문자열로 변환
    for item in data:
        item['date'] = item['date'].strftime('%m.%d')

    sector_name = data[0]['name'] if data else ''

    return JsonResponse({'success': True, 'data': data, 'name': sector_name})
