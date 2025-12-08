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
    from django.db.models import Min

    # 대분류명, 소분류명 순으로 정렬 (테마 없는 종목은 맨 뒤)
    base_qs = Info.objects.filter(is_active=True).prefetch_related('themes__category')

    def sort_by_theme(stocks):
        """대분류, 소분류 순 정렬"""
        result = []
        for stock in stocks:
            themes = list(stock.themes.all())
            if themes:
                # 첫 번째 테마 기준 정렬 키
                first_theme = min(themes, key=lambda t: (t.category.name, t.name))
                result.append((first_theme.category.name, first_theme.name, stock))
            else:
                result.append(('zzz', 'zzz', stock))  # 테마 없는 종목은 뒤로
        result.sort(key=lambda x: (x[0], x[1]))
        return [item[2] for item in result]

    super_stocks = sort_by_theme(base_qs.filter(interest_level='super'))
    normal_stocks = sort_by_theme(base_qs.filter(interest_level='normal'))
    incubator_stocks = sort_by_theme(base_qs.filter(interest_level='incubator'))

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

    stocks = Info.objects.filter(is_active=True)

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
    stock = get_object_or_404(Info.objects.prefetch_related('themes__category'), code=code)

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


def run_fav_commands(stock_code, action):
    """관심 종목 변경 시 명령어 백그라운드 실행"""
    import threading
    import logging
    from django.core.management import call_command

    logger = logging.getLogger(__name__)

    def run():
        logger.info(f'[FAV] {stock_code} 동기화 시작 (action={action})')
        try:
            if action == 'add':
                # 데이터 수집 (전체 기간)
                logger.info(f'[FAV] {stock_code} save_investor_trend 시작')
                call_command('save_investor_trend', code=stock_code, mode='all')
                logger.info(f'[FAV] {stock_code} save_short_selling 시작')
                call_command('save_short_selling', code=stock_code, mode='all')
                logger.info(f'[FAV] {stock_code} save_gongsi_stock 시작')
                call_command('save_gongsi_stock', code=stock_code)
                logger.info(f'[FAV] {stock_code} save_fnguide_report 시작')
                call_command('save_fnguide_report', code=stock_code)
                logger.info(f'[FAV] {stock_code} save_nodaji_stock 시작')
                call_command('save_nodaji_stock', code=stock_code)
            else:  # remove
                # 데이터 삭제
                call_command('save_investor_trend', clear=True, code=stock_code)
                call_command('save_short_selling', clear=True, code=stock_code)
                call_command('save_gongsi_stock', clear=True, code=stock_code)
                call_command('save_fnguide_report', clear=True, code=stock_code)
                call_command('save_nodaji_stock', clear=True, code=stock_code)
            logger.info(f'[FAV] {stock_code} 동기화 완료')
        except Exception as e:
            logger.error(f'[FAV] {stock_code} 동기화 오류: {e}', exc_info=True)
        finally:
            # 완료 시 상태 업데이트
            try:
                from django.db import connection
                connection.close()  # 스레드에서 DB 연결 재설정
                stock = Info.objects.get(code=stock_code)
                if action == 'add':
                    stock.fav_sync_status = 'completed'
                else:
                    stock.fav_sync_status = None  # 삭제 완료 시 상태 초기화
                stock.save(update_fields=['fav_sync_status'])
            except Exception as e:
                logger.error(f'[FAV] {stock_code} 상태 업데이트 오류: {e}', exc_info=True)

    thread = threading.Thread(target=run)
    thread.daemon = True
    thread.start()


def stock_edit(request, code):
    """종목 편집 페이지"""
    stock = get_object_or_404(Info, code=code)

    if request.method == 'POST':
        old_interest_level = stock.interest_level  # 변경 전 값 저장

        interest_level = request.POST.get('interest_level', '')
        new_interest_level = interest_level if interest_level else None
        stock.interest_level = new_interest_level
        stock.is_holding = request.POST.get('is_holding') == 'on'
        stock.investment_point = request.POST.get('investment_point', '')
        stock.risk = request.POST.get('risk', '')
        stock.analysis = request.POST.get('analysis', '')
        stock.save()

        # 업종 저장 (ManyToMany)
        from .models import Theme
        theme_ids = request.POST.getlist('themes')
        stock.themes.set(Theme.objects.filter(id__in=theme_ids))

        # 관심 종목 변경 시 데이터 수집/삭제
        if old_interest_level is None and new_interest_level is not None:
            # 관심 등록: 데이터 수집
            stock.fav_sync_status = 'syncing'
            stock.save(update_fields=['fav_sync_status'])
            run_fav_commands(code, 'add')
            messages.success(request, f'{stock.name} 정보가 저장되었습니다. (데이터 수집 중...)')
        elif old_interest_level is not None and new_interest_level is None:
            # 관심 해제: 데이터 삭제
            stock.fav_sync_status = 'deleting'
            stock.save(update_fields=['fav_sync_status'])
            run_fav_commands(code, 'remove')
            messages.success(request, f'{stock.name} 정보가 저장되었습니다. (데이터 삭제 중...)')
        else:
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

    # 업종 (전체 및 현재 종목의 업종)
    from .models import ThemeCategory
    theme_categories = ThemeCategory.objects.prefetch_related('themes').all()
    stock_theme_ids = list(stock.themes.values_list('id', flat=True))

    context = {
        'stock': stock,
        'interest_choices': interest_choices,
        'theme_categories': theme_categories,
        'stock_theme_ids': stock_theme_ids,
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

            # 날짜순 정렬 (최신순)
            def parse_date_for_sort(item):
                date_str = item.get('date', '')
                # "2024.12.06" 형식
                if '.' in date_str and len(date_str) >= 10:
                    try:
                        return datetime.strptime(date_str[:10], '%Y.%m.%d')
                    except ValueError:
                        pass
                # "12월 6일" 형식
                if '월' in date_str and '일' in date_str:
                    try:
                        import re
                        match = re.match(r'(\d+)월\s*(\d+)일', date_str)
                        if match:
                            month, day = int(match.group(1)), int(match.group(2))
                            return datetime(datetime.now().year, month, day)
                    except:
                        pass
                return datetime.min

            results.sort(key=parse_date_for_sort, reverse=True)

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


def settings(request):
    """설정 페이지"""
    from .models import ThemeCategory, CronJob

    categories = ThemeCategory.objects.prefetch_related('themes').all()
    cron_jobs = CronJob.objects.all()

    context = {
        'categories': categories,
        'cron_jobs': cron_jobs,
    }
    return render(request, 'stocks/settings.html', context)


def etf(request):
    """ETF 페이지"""
    from .models import InfoETF

    # 관심 ETF 목록 (is_active=True)
    etfs = InfoETF.objects.filter(is_active=True).order_by('-market_cap')

    context = {
        'etfs': etfs,
    }
    return render(request, 'stocks/etf.html', context)


def etf_detail(request, code):
    """ETF 상세 페이지"""
    from .models import InfoETF, DailyChartETF, WeeklyChartETF, MonthlyChartETF

    etf = get_object_or_404(InfoETF, code=code)

    # 일봉 차트 데이터 (최근 240일)
    daily_charts = list(DailyChartETF.objects.filter(
        etf=etf
    ).order_by('-date')[:240])
    daily_charts.reverse()

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

    # 주봉 차트 데이터 (최근 104주 = 2년)
    weekly_charts = list(WeeklyChartETF.objects.filter(
        etf=etf
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
    monthly_charts = list(MonthlyChartETF.objects.filter(
        etf=etf
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
        'etf': etf,
        'daily_candle_data': json.dumps(daily_candle_data),
        'daily_volume_data': json.dumps(daily_volume_data),
        'weekly_candle_data': json.dumps(weekly_candle_data),
        'weekly_volume_data': json.dumps(weekly_volume_data),
        'monthly_candle_data': json.dumps(monthly_candle_data),
        'monthly_volume_data': json.dumps(monthly_volume_data),
    }
    return render(request, 'stocks/etf_detail.html', context)


@require_POST
def add_etf(request):
    """ETF 추가 API - 네이버 금융에서 크롤링"""
    import requests
    from bs4 import BeautifulSoup

    code = request.POST.get('code', '').strip()

    if not code:
        return JsonResponse({'error': '종목코드를 입력해주세요.'}, status=400)

    # 6자리 영숫자 검증
    if not code.isalnum() or len(code) != 6:
        return JsonResponse({'error': '종목코드는 6자리입니다.'}, status=400)

    # 네이버 금융 크롤링
    url = f'https://finance.naver.com/item/main.naver?code={code}'
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except Exception as e:
        return JsonResponse({'error': f'네이버 금융 접속 실패: {str(e)}'}, status=500)

    soup = BeautifulSoup(response.text, 'lxml')

    # 종목명 추출
    name_elem = soup.select_one('#middle > div.h_company > div.wrap_company > h2 > a')
    if not name_elem:
        return JsonResponse({'error': '종목 정보를 찾을 수 없습니다. ETF 코드를 확인해주세요.'}, status=400)

    name = name_elem.get_text(strip=True)

    # ETF인지 확인 (ETF 섹션이 있는지)
    etf_section = soup.select_one('#content > div.section.etf_asset')
    if not etf_section:
        return JsonResponse({'error': f'{name}은(는) ETF가 아닙니다.'}, status=400)

    # 현재가 추출
    current_price = None
    price_elem = soup.select_one('#chart_area > div.rate_info > div > p.no_today > em > span.blind')
    if price_elem:
        try:
            current_price = int(price_elem.get_text(strip=True).replace(',', ''))
        except:
            pass

    # 등락률 추출
    change_rate = None
    rate_elem = soup.select_one('#chart_area > div.rate_info > div > p.no_exday > em:nth-child(4) > span.blind')
    if rate_elem:
        try:
            rate_text = rate_elem.get_text(strip=True).replace('%', '')
            change_rate = float(rate_text)
            # 하락인지 확인
            down_elem = soup.select_one('#chart_area > div.rate_info > div > p.no_exday > em.no_down')
            if down_elem:
                change_rate = -abs(change_rate)
        except:
            pass

    # NAV 추출 (사용자 제공 셀렉터: #on_board_last_nav)
    nav = None
    nav_elem = soup.select_one('#on_board_last_nav')
    if nav_elem:
        try:
            nav = int(nav_elem.get_text(strip=True).replace(',', ''))
        except:
            pass

    # 시가총액 추출 ("시가총액" th를 찾아서 옆 td 값 가져오기)
    # "1조 6,296억원" -> 16296, "2,345억원" -> 2345 (억원 단위)
    market_cap = None
    tab_con1 = soup.select_one('#tab_con1')
    if tab_con1:
        for th in tab_con1.find_all('th'):
            if '시가총액' in th.get_text():
                td = th.find_next_sibling('td')
                if td:
                    import re
                    text = td.get_text(strip=True)
                    total = 0
                    # 조 단위 추출 (1조 = 10000억)
                    jo_match = re.search(r'(\d+)조', text.replace(',', ''))
                    if jo_match:
                        total += int(jo_match.group(1)) * 10000
                    # 억 단위 추출
                    eok_match = re.search(r'(\d+)억', text.replace(',', ''))
                    if eok_match:
                        total += int(eok_match.group(1))
                    market_cap = total if total > 0 else None
                break

    # 구성종목 추출 (td.per 클래스로 구성비중 찾기)
    holdings = []
    holdings_rows = soup.select('#content > div.section.etf_asset > table > tbody > tr')
    for row in holdings_rows:
        name_elem = row.select_one('td:first-child')
        ratio_elem = row.select_one('td.per')
        if name_elem and ratio_elem:
            holding_name = name_elem.get_text(strip=True)
            holding_ratio = ratio_elem.get_text(strip=True)
            if holding_name and holding_name != '합계':
                holdings.append({'name': holding_name, 'ratio': holding_ratio})
        if len(holdings) >= 10:
            break

    # 저장하지 않고 데이터만 반환
    return JsonResponse({
        'success': True,
        'code': code,
        'name': name,
        'current_price': current_price,
        'change_rate': change_rate,
        'nav': nav,
        'market_cap': market_cap,
        'holdings': holdings,
    })


def fetch_etf_chart(etf, timeframe, mode='all'):
    """
    ETF 차트 데이터 조회 및 저장 (네이버 API)

    Args:
        etf: InfoETF 객체
        timeframe: 'day', 'week', 'month'
        mode: 'all' or 'last'

    Returns:
        (created_count, updated_count)
    """
    import requests as http_requests
    from .models import DailyChartETF, WeeklyChartETF, MonthlyChartETF

    # 기간 계산
    today = datetime.now()
    if mode == 'all':
        if timeframe == 'day':
            start_date = today - timedelta(days=730)  # 2년
        elif timeframe == 'week':
            start_date = today - timedelta(days=1460)  # 4년
        else:  # month
            start_date = today - timedelta(days=2190)  # 6년
    else:  # last
        if timeframe == 'day':
            start_date = today - timedelta(days=30)
        elif timeframe == 'week':
            start_date = today - timedelta(weeks=12)
        else:  # month
            start_date = today - timedelta(days=365)

    start_str = start_date.strftime('%Y%m%d')
    end_str = today.strftime('%Y%m%d')

    # 네이버 API 호출
    url = 'https://api.finance.naver.com/siseJson.naver'
    params = {
        'symbol': etf.code,
        'requestType': '1',
        'startTime': start_str,
        'endTime': end_str,
        'timeframe': timeframe,
    }
    headers = {'User-Agent': 'Mozilla/5.0'}

    try:
        response = http_requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
    except Exception:
        return (0, 0)

    # JSON 파싱 (네이버 응답은 전처리 필요)
    try:
        text = response.text.strip()
        text = text.replace("'", '"')
        text = text.replace('\n', '').replace('\t', '')
        text = text.replace(',]', ']')
        data = json.loads(text)
    except json.JSONDecodeError:
        return (0, 0)

    if not data or len(data) < 2:
        return (0, 0)

    chart_data = data[1:]  # 헤더 제외

    # 모델 선택
    if timeframe == 'day':
        ChartModel = DailyChartETF
    elif timeframe == 'week':
        ChartModel = WeeklyChartETF
    else:
        ChartModel = MonthlyChartETF

    # DB 저장
    created_count = 0
    updated_count = 0

    for row in chart_data:
        if len(row) < 6:
            continue

        try:
            date_str = str(row[0])
            date = datetime.strptime(date_str, '%Y%m%d').date()

            _, created = ChartModel.objects.update_or_create(
                etf=etf,
                date=date,
                defaults={
                    'opening_price': int(row[1]),
                    'high_price': int(row[2]),
                    'low_price': int(row[3]),
                    'closing_price': int(row[4]),
                    'trading_volume': int(row[5]),
                }
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

        except Exception:
            pass

    return (created_count, updated_count)


@require_POST
def save_etf(request):
    """ETF 관심종목 저장 API"""
    from .models import InfoETF

    code = request.POST.get('code', '').strip()
    name = request.POST.get('name', '').strip()
    current_price = request.POST.get('current_price')
    change_rate = request.POST.get('change_rate')
    nav = request.POST.get('nav')
    market_cap = request.POST.get('market_cap')
    holdings = request.POST.get('holdings', '[]')

    if not code or not name:
        return JsonResponse({'error': '종목코드와 종목명이 필요합니다.'}, status=400)

    # JSON 파싱
    import json
    try:
        holdings_list = json.loads(holdings)
    except:
        holdings_list = []

    # 숫자 변환
    try:
        current_price = int(current_price) if current_price else None
    except:
        current_price = None

    try:
        change_rate = float(change_rate) if change_rate else None
    except:
        change_rate = None

    try:
        nav = int(nav) if nav else None
    except:
        nav = None

    try:
        market_cap = int(market_cap) if market_cap else None
    except:
        market_cap = None

    # InfoETF 저장 (있으면 업데이트, 없으면 생성)
    etf, created = InfoETF.objects.update_or_create(
        code=code,
        defaults={
            'name': name,
            'current_price': current_price,
            'change_rate': change_rate,
            'nav': nav,
            'market_cap': market_cap,
            'holdings': holdings_list,
            'is_active': True,
        }
    )

    # 새로 생성된 ETF인 경우 차트 데이터도 저장 (mode=all)
    chart_result = None
    if created:
        daily = fetch_etf_chart(etf, 'day', 'all')
        weekly = fetch_etf_chart(etf, 'week', 'all')
        monthly = fetch_etf_chart(etf, 'month', 'all')
        chart_result = {
            'daily': f'+{daily[0]}/={daily[1]}',
            'weekly': f'+{weekly[0]}/={weekly[1]}',
            'monthly': f'+{monthly[0]}/={monthly[1]}',
        }

    return JsonResponse({
        'success': True,
        'created': created,
        'code': etf.code,
        'name': etf.name,
        'chart': chart_result,
    })


@require_POST
def category_add(request):
    """대분류 추가 API"""
    from .models import ThemeCategory

    name = request.POST.get('name', '').strip()

    if not name:
        return JsonResponse({'error': '대분류명을 입력해주세요.'}, status=400)

    if len(name) > 20:
        return JsonResponse({'error': '대분류명은 20자 이하로 입력해주세요.'}, status=400)

    if ThemeCategory.objects.filter(name=name).exists():
        return JsonResponse({'error': '이미 존재하는 대분류입니다.'}, status=400)

    category = ThemeCategory.objects.create(name=name)

    return JsonResponse({
        'success': True,
        'id': category.id,
        'name': category.name,
    })


@require_POST
def category_delete(request, category_id):
    """대분류 삭제 API"""
    from .models import ThemeCategory

    category = get_object_or_404(ThemeCategory, id=category_id)
    category.delete()

    return JsonResponse({'success': True})


@require_POST
def theme_add(request):
    """소분류 추가 API"""
    from .models import Theme, ThemeCategory

    category_id = request.POST.get('category_id', '')
    name = request.POST.get('name', '').strip()

    if not category_id:
        return JsonResponse({'error': '대분류를 선택해주세요.'}, status=400)

    if not name:
        return JsonResponse({'error': '소분류명을 입력해주세요.'}, status=400)

    if len(name) > 20:
        return JsonResponse({'error': '소분류명은 20자 이하로 입력해주세요.'}, status=400)

    category = get_object_or_404(ThemeCategory, id=category_id)

    if Theme.objects.filter(category=category, name=name).exists():
        return JsonResponse({'error': '같은 대분류에 이미 존재하는 소분류입니다.'}, status=400)

    theme = Theme.objects.create(category=category, name=name)

    return JsonResponse({
        'success': True,
        'id': theme.id,
        'category_id': category.id,
        'name': theme.name,
    })


@require_POST
def theme_delete(request, theme_id):
    """소분류 삭제 API"""
    from .models import Theme

    theme = get_object_or_404(Theme, id=theme_id)
    theme.delete()

    return JsonResponse({'success': True})


@require_GET
def search_google_news(request):
    """Google News 검색 API - Playwright 사용"""
    from urllib.parse import quote

    keyword = request.GET.get('keyword', '')

    if not keyword:
        return JsonResponse({'error': '검색어가 필요합니다.'}, status=400)

    url = f'https://news.google.com/search?q={quote(keyword)}&hl=ko&gl=KR&ceid=KR%3Ako'

    try:
        from playwright.sync_api import sync_playwright
        from bs4 import BeautifulSoup

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until='networkidle', timeout=30000)

            # 충분히 대기
            page.wait_for_timeout(3000)

            html = page.content()
            browser.close()

            soup = BeautifulSoup(html, 'html.parser')
            results = []

            # Google News: div.UW0SDc 내에서 기사 링크 찾기
            container = soup.select_one('div.UW0SDc')
            if not container:
                container = soup

            # 모든 기사 링크 찾기 (./articles/ 또는 ./read/로 시작하는 링크)
            all_links = container.find_all('a', href=True)
            seen_titles = set()

            for a in all_links:
                href = a.get('href', '')
                text = a.get_text(strip=True)

                # 기사 링크만 처리
                if not (href.startswith('./articles/') or href.startswith('./read/')):
                    continue
                if len(text) < 10:  # 제목은 최소 10자
                    continue
                if text in seen_titles:  # 중복 제거
                    continue

                seen_titles.add(text)
                title = text
                link = 'https://news.google.com' + href[1:]

                # 상위 요소들에서 출처와 시간 찾기
                source = ''
                date = ''

                # 여러 단계의 부모 요소 탐색
                current = a
                for _ in range(10):
                    current = current.find_parent()
                    if not current:
                        break

                    # 시간 찾기
                    if not date:
                        time_el = current.find('time')
                        if time_el:
                            datetime_attr = time_el.get('datetime', '')
                            if datetime_attr:
                                try:
                                    dt = datetime.fromisoformat(datetime_attr.replace('Z', '+00:00'))
                                    date = dt.strftime('%Y-%m-%d %H:%M')
                                except:
                                    date = time_el.get_text(strip=True)
                            else:
                                date = time_el.get_text(strip=True)

                    # 출처 찾기 (보통 이미지 옆에 있거나 별도 div에 있음)
                    if not source:
                        for el in current.find_all(['div', 'span', 'a'], recursive=False):
                            el_text = el.get_text(strip=True)
                            # '더보기' 제거
                            el_text = el_text.replace('더보기', '').strip()
                            if el_text and 2 <= len(el_text) <= 20 and el_text != title:
                                if not any(x in el_text for x in ['시간', '분 전', '일 전', '주 전', '검색', '관련']):
                                    # 제목의 일부가 아닌지 확인
                                    if el_text not in title:
                                        source = el_text
                                        break

                    # 둘 다 찾았으면 종료
                    if date and source:
                        break

                results.append({
                    'title': title,
                    'source': source,
                    'date': date,
                    'link': link,
                })

                if len(results) >= 15:
                    break

            # 날짜순 정렬 (최신순)
            def parse_news_date(item):
                date_str = item.get('date', '')
                if not date_str:
                    return datetime.min
                try:
                    if '-' in date_str and ':' in date_str:
                        return datetime.strptime(date_str[:16], '%Y-%m-%d %H:%M')
                    if '-' in date_str:
                        return datetime.strptime(date_str[:10], '%Y-%m-%d')
                except:
                    pass
                return datetime.min

            results.sort(key=parse_news_date, reverse=True)

        return JsonResponse({
            'success': True,
            'keyword': keyword,
            'results': results,
        })

    except Exception as e:
        import traceback
        return JsonResponse({'error': str(e), 'trace': traceback.format_exc()}, status=500)


@require_POST
def cronjob_save(request):
    """크론잡 저장 API (추가/수정)"""
    from .models import CronJob
    from datetime import datetime

    job_id = request.POST.get('id', '')
    command = request.POST.get('command', '').strip()
    run_time = request.POST.get('run_time', '').strip()
    weekdays = request.POST.get('weekdays', '1,2,3,4,5').strip()

    if not command:
        return JsonResponse({'error': '명령어를 선택해주세요.'}, status=400)
    if not run_time:
        return JsonResponse({'error': '실행시간을 입력해주세요.'}, status=400)

    # command에서 name 자동 생성 (첫 번째 단어)
    name = command.split()[0] if command else ''

    # 시간 파싱
    try:
        time_obj = datetime.strptime(run_time, '%H:%M').time()
    except ValueError:
        return JsonResponse({'error': '시간 형식이 올바르지 않습니다.'}, status=400)

    if job_id:
        # 수정
        job = get_object_or_404(CronJob, id=job_id)
        job.name = name
        job.command = command
        job.run_time = time_obj
        job.weekdays = weekdays
        job.save()
    else:
        # 추가
        job = CronJob.objects.create(
            name=name,
            command=command,
            run_time=time_obj,
            weekdays=weekdays,
        )

    return JsonResponse({
        'success': True,
        'id': job.id,
        'name': job.name,
    })


@require_POST
def cronjob_delete(request, job_id):
    """크론잡 삭제 API"""
    from .models import CronJob

    job = get_object_or_404(CronJob, id=job_id)
    job.delete()

    return JsonResponse({'success': True})


@require_POST
def cronjob_toggle(request, job_id):
    """크론잡 활성화 토글 API"""
    from .models import CronJob

    job = get_object_or_404(CronJob, id=job_id)
    is_active = request.POST.get('is_active', 'false')
    job.is_active = is_active.lower() in ('true', '1', 'on')
    job.save()

    return JsonResponse({
        'success': True,
        'is_active': job.is_active,
    })
