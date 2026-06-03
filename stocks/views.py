import json
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from django.conf import settings as django_settings
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from decouple import config
from telethon import TelegramClient
from django.views.decorators.http import require_POST
from .models import Info, Financial, DailyChart, WeeklyChart, MonthlyChart, Report, Nodaji, Gongsi, IndexChart, MarketTrend, InvestorTrend, ShortSelling, MarketDiary, StockDiary, StockEvent, SectorEvent, ETFEvent

import unicodedata
import re as _re


def _normalize_gongsi(text):
    if not text:
        return ''
    text = unicodedata.normalize('NFC', text)
    for dot in ['ㆍ', '\u00b7', '\u2219', '\u2022', '\u0387', '\u30fb']:
        text = text.replace(dot, '')
    text = text.replace('\uff08', '(').replace('\uff09', ')')
    text = _re.sub(r'\s+', '', text)
    for dash in ['\u2212', '\u2013', '\u2014', '\u30fc', '\u2500']:
        text = text.replace(dash, '-')
    return text


_POSITIVE_KEYWORDS = [
    '자기주식소각',
    '기업가치제고계획',
    '자기주식취득결과보고서',
    '자기주식취득결정',
    '주식배당결정',
    '무상증자결정',
    '특허권취득',
    '현금현물배당결정',
]
_NEGATIVE_KEYWORDS = [
    '회생절차',
    '법정관리',
    '거래정지',
    '관리종목지정',
    '상장폐지',
    '감사의견거절',
    '감사의견한정',
    '부도',
    '횡령',
    '배임',
    '무상감자',
    '공급계약해지',
    '자기주식처분결정',
    '유상증자결정',
    '전환사채권발행',
    '신주인수권부사채권발행',
    '교환사채권발행',
    '소송등의제기',
    '영업정지',
    '시정명령',
    '불성실공시',
]
_REVIEW_KEYWORDS = [
    '영업(잠정)실적',
    '매출액또는손익구조',
    '임원주요주주특정증권',
    '주식등의대량보유',
    '타법인주식및출자증권취득',
    '영업양수',
    '영업양도',
    '회사합병결정',
    '회사분할결정',
    '단일판매공급계약체결',
    '특별관계자',
    '최대주주변경',
    '공개매수',
]


def _classify_gongsi(title):
    normalized = _normalize_gongsi(title)
    if not normalized:
        return None
    if '자기주식취득' in normalized and '신탁계약' in normalized:
        return '검토'
    for kw in _NEGATIVE_KEYWORDS:
        if _normalize_gongsi(kw) in normalized:
            return '악재'
    for kw in _POSITIVE_KEYWORDS:
        if _normalize_gongsi(kw) in normalized:
            return '호재'
    for kw in _REVIEW_KEYWORDS:
        if _normalize_gongsi(kw) in normalized:
            return '검토'
    return None


def index(request):
    """종목 대시보드 (관심종목)"""
    from django.db.models import Max

    # 대분류명, 소분류명 순으로 정렬 (테마 없는 종목은 맨 뒤)
    base_qs = Info.objects.filter(is_active=True).prefetch_related('themes__category', 'custom_sectors')

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
    waiting_stocks = sort_by_theme(base_qs.filter(interest_level='waiting'))

    # ============ 대시보드 카드 ============
    target_stocks = sort_by_theme(base_qs.filter(interest_level__in=['super', 'normal', 'waiting']))

    # 카드 A: 장기 신호 (60일 신고거래량)
    card_a_stocks = []  # 급등 (양봉, MA20 위)
    card_a_down_stocks = []  # 급락 (음봉, MA20 아래)

    for stock in target_stocks:
        # 최근 120일 일봉 데이터 (MA120 계산용)
        daily_data = list(DailyChart.objects.filter(
            stock=stock
        ).order_by('-date')[:120])

        if len(daily_data) < 60:  # 최소 60일 필요
            continue

        # 오늘 데이터
        today = daily_data[0]

        # 60일 중 최대 거래량
        max_volume_60 = max(d.trading_volume for d in daily_data[:60])

        # 조건 1: 오늘 거래량 == 60일 최대 거래량
        if today.trading_volume != max_volume_60 or today.trading_volume <= 0:
            continue

        # 이평선 계산
        ma10 = sum(d.closing_price for d in daily_data[:10]) / 10 if len(daily_data) >= 10 else 0
        ma20 = sum(d.closing_price for d in daily_data[:20]) / 20 if len(daily_data) >= 20 else 0
        ma60 = sum(d.closing_price for d in daily_data[:60]) / 60 if len(daily_data) >= 60 else 0
        ma120 = sum(d.closing_price for d in daily_data[:120]) / 120 if len(daily_data) >= 120 else 0

        # MA120 위 여부 (정배열 체크)
        above_ma120 = today.closing_price > ma120 if ma120 else False

        # 52주(약 250일) 최고가 대비 위치 (마이너스 %)
        high_52w = stock.high_250 or stock.year_high
        high_position = 0
        if high_52w and high_52w > 0:
            high_position = round((today.closing_price / high_52w - 1) * 100, 1)

        # 등락률
        change_rate = stock.change_rate or 0

        # 거래대금 (백만원 → 억원 변환)
        trading_value = round(today.trading_value / 100) if today.trading_value else 0

        # 10일 스파크라인 데이터 (종가)
        sparkline = [d.closing_price for d in daily_data[:10]]
        sparkline.reverse()  # 과거 → 현재 순서로

        stock_data = {
            'stock': stock,
            'change_rate': change_rate,
            'above_ma120': above_ma120,
            'high_position': high_position,
            'trading_value': trading_value,
            'sparkline': sparkline,
        }

        # 급등: 양봉 + MA20 위
        is_bullish = today.closing_price >= today.opening_price
        above_ma20 = today.closing_price > ma20

        if is_bullish and above_ma20:
            card_a_stocks.append(stock_data)
        # 급락: 음봉 + MA20 아래
        elif not is_bullish and not above_ma20:
            card_a_down_stocks.append(stock_data)

    # 등락률 순으로 정렬
    card_a_stocks.sort(key=lambda x: x['change_rate'], reverse=True)
    card_a_down_stocks.sort(key=lambda x: x['change_rate'])  # 급락은 낮은 순

    # 카드 A에 포함된 종목 코드 (중복 제거용)
    card_a_codes = {item['stock'].code for item in card_a_stocks} | {item['stock'].code for item in card_a_down_stocks}

    # 카드 B: 단기 신호 (20일 신고거래량)
    card_b_stocks = []  # 급등 (양봉, MA20 위)
    card_b_down_stocks = []  # 급락 (음봉, MA20 아래)

    for stock in target_stocks:
        # 카드 A에 이미 있는 종목은 제외
        if stock.code in card_a_codes:
            continue

        # 최근 120일 일봉 데이터 (MA120 계산용)
        daily_data = list(DailyChart.objects.filter(
            stock=stock
        ).order_by('-date')[:120])

        if len(daily_data) < 20:  # 최소 20일 필요
            continue

        # 오늘 데이터
        today = daily_data[0]

        # 20일 중 최대 거래량
        recent_20 = daily_data[:20]
        max_volume_20 = max(d.trading_volume for d in recent_20)

        # 조건 1: 오늘 거래량 == 20일 최대 거래량
        if today.trading_volume != max_volume_20 or today.trading_volume <= 0:
            continue

        # 이평선 계산
        ma10 = sum(d.closing_price for d in daily_data[:10]) / 10 if len(daily_data) >= 10 else 0
        ma20 = sum(d.closing_price for d in daily_data[:20]) / 20 if len(daily_data) >= 20 else 0
        ma60 = sum(d.closing_price for d in daily_data[:60]) / 60 if len(daily_data) >= 60 else 0
        ma120 = sum(d.closing_price for d in daily_data[:120]) / 120 if len(daily_data) >= 120 else 0

        # MA120 위 여부 (정배열 체크)
        above_ma120 = today.closing_price > ma120 if ma120 else False

        # 52주(약 250일) 최고가 대비 위치 (마이너스 %)
        high_52w = stock.high_250 or stock.year_high
        high_position = 0
        if high_52w and high_52w > 0:
            high_position = round((today.closing_price / high_52w - 1) * 100, 1)

        # 등락률
        change_rate = stock.change_rate or 0

        # 거래대금 (백만원 → 억원 변환)
        trading_value = round(today.trading_value / 100) if today.trading_value else 0

        # 10일 스파크라인 데이터 (종가)
        sparkline = [d.closing_price for d in daily_data[:10]]
        sparkline.reverse()  # 과거 → 현재 순서로

        stock_data = {
            'stock': stock,
            'change_rate': change_rate,
            'above_ma120': above_ma120,
            'high_position': high_position,
            'trading_value': trading_value,
            'sparkline': sparkline,
        }

        # 급등: 양봉 + MA20 위
        is_bullish = today.closing_price >= today.opening_price
        above_ma20 = today.closing_price > ma20

        if is_bullish and above_ma20:
            card_b_stocks.append(stock_data)
        # 급락: 음봉 + MA20 아래
        elif not is_bullish and not above_ma20:
            card_b_down_stocks.append(stock_data)

    # 등락률 순으로 정렬
    card_b_stocks.sort(key=lambda x: x['change_rate'], reverse=True)
    card_b_down_stocks.sort(key=lambda x: x['change_rate'])  # 급락은 낮은 순

    # 카드 A, B에 포함된 종목 코드 (중복 제거용)
    card_ab_codes = card_a_codes | {item['stock'].code for item in card_b_stocks} | {item['stock'].code for item in card_b_down_stocks}

    # 카드 D: 이평선 줍줍 (정배열 눌림목)
    # 정배열 상태에서 MA20 아래로 눌린 종목 포착
    card_d_stocks = []

    for stock in target_stocks:
        # 카드 A, B에 이미 있는 종목은 제외
        if stock.code in card_ab_codes:
            continue

        # 최근 65일 일봉 데이터 (5일전 MA60 계산용)
        daily_data = list(DailyChart.objects.filter(
            stock=stock
        ).order_by('-date')[:65])

        if len(daily_data) < 65:  # MA60 + 5일 필요
            continue

        # 오늘 데이터
        today = daily_data[0]

        # MA20, MA60 계산 (오늘 기준)
        ma20 = sum(d.closing_price for d in daily_data[:20]) / 20
        ma60 = sum(d.closing_price for d in daily_data[:60]) / 60

        # 5일 전 MA60 계산 (기울기 판단용)
        ma60_5days_ago = sum(d.closing_price for d in daily_data[5:65]) / 60

        # === 필터링 조건 (모두 AND) ===
        # 조건 A (정배열): MA20 > MA60
        if ma20 <= ma60:
            continue

        # 조건 B (장기추세): MA60 기울기 > 0 (오늘 MA60 > 5일전 MA60)
        if ma60 <= ma60_5days_ago:
            continue

        # 조건 C (눌림 상태): 종가 < MA20
        if today.closing_price >= ma20:
            continue

        # 조건 D (최대 하락폭): 종가 >= MA60 * 0.90
        if today.closing_price < ma60 * 0.90:
            continue

        # === 추가 정보 계산 ===
        # MA60 대비 괴리율 (얼마나 눌렸는지)
        gap_from_ma60 = round((today.closing_price / ma60 - 1) * 100, 1)

        # 52주(약 250일) 최고가 대비 위치 (마이너스 %)
        high_52w = stock.high_250 or stock.year_high
        high_position = 0
        if high_52w and high_52w > 0:
            high_position = round((today.closing_price / high_52w - 1) * 100, 1)

        # 등락률
        change_rate = stock.change_rate or 0

        # 거래대금 (백만원 → 억원 변환)
        trading_value = round(today.trading_value / 100) if today.trading_value else 0

        # 10일 스파크라인 데이터 (종가)
        sparkline = [d.closing_price for d in daily_data[:10]]
        sparkline.reverse()  # 과거 → 현재 순서로

        card_d_stocks.append({
            'stock': stock,
            'change_rate': change_rate,
            'high_position': high_position,
            'gap_from_ma60': gap_from_ma60,
            'trading_value': trading_value,
            'sparkline': sparkline,
        })

    # MA60 대비 괴리율 순으로 정렬 (0에 가까울수록 = 60일선에 가까울수록 상위)
    card_d_stocks.sort(key=lambda x: x['gap_from_ma60'], reverse=True)

    # 카드 A, B, D에 포함된 종목 코드 (중복 제거용)
    card_abd_codes = card_ab_codes | {item['stock'].code for item in card_d_stocks}

    # 카드 C: 신호 추적 (최근 10거래일 내 조건 충족)
    # 조건: 최근 10거래일 내 60일 OR 20일 신고거래량 + 양봉 + MA20 위
    card_c_stocks = []

    for stock in target_stocks:
        # 카드 A, B, D에 이미 있는 종목은 제외
        if stock.code in card_abd_codes:
            continue

        # 최근 125일 일봉 데이터 (5일 전 시점에서 60일 체크 + MA120 계산용)
        daily_data = list(DailyChart.objects.filter(
            stock=stock
        ).order_by('-date')[:125])

        if len(daily_data) < 65:
            continue

        signal_day = None
        signal_type = None
        signal_days_ago = 0  # 거래일 기준 며칠 전

        # 최근 10거래일 체크 (인덱스 0=오늘, 1=1거래일전, ..., 9=9거래일전)
        for day_idx in range(10):
            check_day = daily_data[day_idx]

            # 조건 1: 양봉 (종가 >= 시가)
            if check_day.closing_price < check_day.opening_price:
                continue

            # 해당 날짜 기준 MA20 계산
            ma20_data = daily_data[day_idx:day_idx + 20]
            if len(ma20_data) < 20:
                continue
            ma20 = sum(d.closing_price for d in ma20_data) / 20

            # 조건 2: 현재가 > MA20
            if check_day.closing_price <= ma20:
                continue

            # 60일 최대 거래량 체크
            volume_60_data = daily_data[day_idx:day_idx + 60]
            if len(volume_60_data) >= 60:
                max_volume_60 = max(d.trading_volume for d in volume_60_data)
                if check_day.trading_volume == max_volume_60 and check_day.trading_volume > 0:
                    signal_day = check_day
                    signal_type = '60일'
                    signal_days_ago = day_idx  # 거래일 기준
                    break

            # 20일 최대 거래량 체크
            volume_20_data = daily_data[day_idx:day_idx + 20]
            if len(volume_20_data) >= 20:
                max_volume_20 = max(d.trading_volume for d in volume_20_data)
                if check_day.trading_volume == max_volume_20 and check_day.trading_volume > 0:
                    signal_day = check_day
                    signal_type = '20일'
                    signal_days_ago = day_idx  # 거래일 기준
                    break

        if not signal_day:
            continue

        # 오늘 데이터
        today = daily_data[0]

        # 52주(약 250일) 최고가 대비 위치
        high_52w = stock.high_250 or stock.year_high
        high_position = 0
        if high_52w and high_52w > 0:
            high_position = round((today.closing_price / high_52w - 1) * 100, 1)

        # 양봉대비 (신호일 종가 대비 현재가 %)
        signal_price_change = 0
        if signal_day.closing_price > 0:
            signal_price_change = round((today.closing_price / signal_day.closing_price - 1) * 100, 1)

        # MA120 위 여부
        ma120 = sum(d.closing_price for d in daily_data[:120]) / 120 if len(daily_data) >= 120 else 0
        above_ma120 = today.closing_price > ma120 if ma120 else False

        # 10일 스파크라인 데이터 (종가)
        sparkline = [d.closing_price for d in daily_data[:10]]
        sparkline.reverse()  # 과거 → 현재 순서로

        card_c_stocks.append({
            'stock': stock,
            'signal_type': signal_type,
            'signal_days_ago': signal_days_ago,
            'signal_price_change': signal_price_change,
            'high_position': high_position,
            'sparkline': sparkline,
            'above_ma120': above_ma120,
            'signal_date': signal_day.date.strftime('%Y-%m-%d'),
            'signal_open': signal_day.opening_price,
            'signal_high': signal_day.high_price,
            'signal_low': signal_day.low_price,
            'signal_close': signal_day.closing_price,
            'current_price': stock.current_price,
        })

    # 양봉대비 순으로 정렬 (하락폭 작은 순)
    card_c_stocks.sort(key=lambda x: x['signal_price_change'], reverse=True)

    # ============ 리포트 카드 ============
    # 거래일 기준 최근 3거래일 가져오기
    recent_3_trading_dates = list(DailyChart.objects.values_list('date', flat=True)
                                .order_by('-date').distinct()[:3])

    card_report_stocks = []
    if recent_3_trading_dates:
        # 최근 3거래일 내 리포트 조회 (관심종목만)
        reports = Report.objects.filter(
            stock__in=target_stocks,
            date__gte=min(recent_3_trading_dates)
        ).select_related('stock').order_by('stock', 'date', '-target_price')

        # 종목+날짜 별로 목표가 가장 높은 리포트만 선택, 총 개수 카운트
        report_by_stock_date = defaultdict(list)
        for report in reports:
            key = (report.stock.code, report.date)
            report_by_stock_date[key].append(report)

        # 종목별로 그룹화 (가장 최신 날짜의 목표가 가장 높은 리포트)
        stock_reports = defaultdict(list)
        for (code, date), rpts in report_by_stock_date.items():
            stock_reports[code].extend(rpts)

        for code, rpts in stock_reports.items():
            # 가장 최신 날짜 기준
            latest_date = max(r.date for r in rpts)
            latest_reports = [r for r in rpts if r.date == latest_date]

            # 목표가 가장 높은 것 선택
            best_report = max(latest_reports, key=lambda r: r.target_price or 0)
            total_count = len(rpts)  # 해당 종목의 전체 리포트 개수

            stock = best_report.stock

            # 괴리율 계산 (목표가 vs 현재가)
            gap_rate = 0
            if best_report.target_price and stock.current_price:
                gap_rate = round((best_report.target_price / stock.current_price - 1) * 100, 1)

            card_report_stocks.append({
                'stock': stock,
                'change_rate': stock.change_rate or 0,
                'title': best_report.title,
                'target_price': best_report.target_price,
                'gap_rate': gap_rate,
                'date': best_report.date,
                'provider': best_report.provider,
                'total_count': total_count,
            })

    # 괴리율 높은 순 정렬
    card_report_stocks.sort(key=lambda x: x['gap_rate'], reverse=True)

    # ============ 노다지 카드 ============
    # 거래일 기준 최근 5거래일 가져오기
    recent_5_trading_dates = list(DailyChart.objects.values_list('date', flat=True)
                                .order_by('-date').distinct()[:5])

    card_nodaji_stocks = []
    if recent_5_trading_dates:
        # 최근 5거래일 내 노다지 조회 (관심종목만)
        nodajis = Nodaji.objects.filter(
            stock__in=target_stocks,
            date__gte=min(recent_5_trading_dates)
        ).select_related('stock').order_by('-date')

        # 종목별로 가장 최신 노다지만
        seen_codes = set()
        for nodaji in nodajis:
            if nodaji.stock.code in seen_codes:
                continue
            seen_codes.add(nodaji.stock.code)

            stock = nodaji.stock
            card_nodaji_stocks.append({
                'stock': stock,
                'nodaji_id': nodaji.id,
                'change_rate': stock.change_rate or 0,
                'title': nodaji.title,
                'date': nodaji.date,
                'link': nodaji.link,
            })

    # 등락율 순 정렬
    card_nodaji_stocks.sort(key=lambda x: x['change_rate'], reverse=True)

    # ============ 현황 테이블 ============
    # --- 공시 분류 로직 ---
    # 관심종목 최근실적 한번에 조회
    from .models import StockQuestionReport as _SQR
    _recent_perf_map = {}  # stock_code → report text
    for sqr in _SQR.objects.filter(stock__in=target_stocks, question='실적확인').only('stock_id', 'report'):
        _recent_perf_map[sqr.stock_id] = sqr.report

    # 관심종목 공시 한번에 조회 (최근 날짜 기준, 3일 초과 리셋)
    from datetime import date as _date_cls
    from django.db.models import Max as _Max
    _gongsi_latest = Gongsi.objects.filter(
        stock__in=target_stocks
    ).aggregate(_Max('date'))['date__max']

    _gongsi_map = {}  # stock_code → (분류, 제목)
    if _gongsi_latest and (_date_cls.today() - _gongsi_latest).days <= 3:
        _gongsi_qs = Gongsi.objects.filter(stock__in=target_stocks, date=_gongsi_latest)
        _gongsi_by_stock = {}
        for g in _gongsi_qs:
            _gongsi_by_stock.setdefault(g.stock_id, []).append(g)
        for code, glist in _gongsi_by_stock.items():
            result_cat, result_title = None, ''
            for g in glist:
                cat = _classify_gongsi(g.title)
                if cat == '악재':
                    result_cat, result_title = '악재', g.title
                    break  # 악재 우선, 즉시 종료
                elif cat == '호재' and result_cat != '호재':
                    result_cat, result_title = '호재', g.title
                elif cat == '검토' and result_cat is None:
                    result_cat, result_title = '검토', g.title
            if result_cat:
                _gongsi_map[code] = (result_cat, result_title)

    card_d_codes = {item['stock'].code for item in card_d_stocks}
    status_stocks = []
    for stock in target_stocks:
        daily_data = list(DailyChart.objects.filter(stock=stock).order_by('-date')[:130])
        if not daily_data:
            _gc = _gongsi_map.get(stock.code)
            status_stocks.append({'stock': stock, 'level': stock.interest_level, 'vol_high_20': False, 'vol_high_60': False, 'ma_align': '', 'pullback': None, 'pullback_label': '', 'has_report': False, 'has_nodaji': False, 'inst_label': '', 'frgn_label': '', 'gongsi_cat': _gc[0] if _gc else '', 'gongsi_title': _gc[1] if _gc else '', 'has_alert': False, 'alert_conditions': '', 'recent_perf': _recent_perf_map.get(stock.code, '')})
            continue

        today = daily_data[0]
        today_vol = today.trading_volume or 0

        max_vol_20 = max((d.trading_volume or 0) for d in daily_data[:20]) if len(daily_data) >= 2 else 0
        max_vol_60 = max((d.trading_volume or 0) for d in daily_data[:60]) if len(daily_data) >= 2 else 0

        # 배열 판단
        ma_align = ''
        if len(daily_data) >= 125:
            ma5 = sum(d.closing_price for d in daily_data[:5]) / 5
            ma20 = sum(d.closing_price for d in daily_data[:20]) / 20
            ma60 = sum(d.closing_price for d in daily_data[:60]) / 60
            ma120 = sum(d.closing_price for d in daily_data[:120]) / 120
            ma120_prev = sum(d.closing_price for d in daily_data[5:125]) / 120
            m = 1.005
            if (ma5 > ma20 * m and ma20 > ma60 * m and ma60 > ma120 * m
                    and ma120 > ma120_prev):
                ma_align = 'bull'
            elif (ma5 * m < ma20 and ma20 * m < ma60 and ma60 * m < ma120
                  and ma120 < ma120_prev):
                ma_align = 'bear'
            else:
                ma_align = 'mixed'

        # 눌림목 판단 (정배열일 때만)
        pullback = None
        pullback_label = ''
        if ma_align == 'bull' and len(daily_data) >= 20:
            _ma20 = sum(d.closing_price for d in daily_data[:20]) / 20
            gap_pct = round((today.closing_price - _ma20) / _ma20 * 100, 1)
            pullback = gap_pct
            if gap_pct > 5:
                pullback_label = '과열'
            elif gap_pct > 2:
                pullback_label = '추세중'
            elif gap_pct > -2:
                pullback_label = '얕은눌림'
            elif gap_pct > -5:
                pullback_label = '깊은눌림'
            else:
                pullback_label = '이탈'

        # 10일 스파크라인
        sparkline = [d.closing_price for d in daily_data[:10]]
        sparkline.reverse()

        # 신호추적 (최근 10거래일 내 신고거래량+양봉+MA20위)
        signal_info = None
        # card_c에서 먼저 찾기
        for item in card_c_stocks:
            if item['stock'].code == stock.code:
                signal_info = item
                break
        # 없으면 직접 계산 (card_a/b/d에 있어서 card_c에서 제외된 종목)
        if not signal_info and len(daily_data) >= 65:
            for day_idx in range(10):
                check_day = daily_data[day_idx]
                if check_day.closing_price < check_day.opening_price:
                    continue
                ma20_data = daily_data[day_idx:day_idx + 20]
                if len(ma20_data) < 20:
                    continue
                ma20_val = sum(d.closing_price for d in ma20_data) / 20
                if check_day.closing_price <= ma20_val:
                    continue
                vol_60_data = daily_data[day_idx:day_idx + 60]
                vol_20_data = daily_data[day_idx:day_idx + 20]
                is_60 = len(vol_60_data) >= 60 and check_day.trading_volume == max(d.trading_volume for d in vol_60_data) and check_day.trading_volume > 0
                is_20 = not is_60 and len(vol_20_data) >= 20 and check_day.trading_volume == max(d.trading_volume for d in vol_20_data) and check_day.trading_volume > 0
                if is_60 or is_20:
                    sig_change = round((today.closing_price / check_day.closing_price - 1) * 100, 1) if check_day.closing_price > 0 else 0
                    signal_info = {
                        'signal_days_ago': day_idx,
                        'signal_price_change': sig_change,
                        'signal_date': check_day.date.strftime('%Y-%m-%d'),
                        'signal_open': check_day.opening_price,
                        'signal_close': check_day.closing_price,
                        'current_price': stock.current_price,
                        'stock': stock,
                    }
                    break

        # 기관/외국인 수급 분석
        inst_label = ''
        frgn_label = ''
        inv_data = list(InvestorTrend.objects.filter(stock=stock).order_by('-date')[:20])
        if inv_data:
            # 20일 최대 체크
            inst_values = [d.institution for d in inv_data]
            frgn_values = [d.foreign for d in inv_data]
            if inst_values[0] > 0 and inst_values[0] >= max(inst_values):
                inst_label = '20일'
            if frgn_values[0] > 0 and frgn_values[0] >= max(frgn_values):
                frgn_label = '20일'
            # 연속 플러스 체크 (20일 최대가 아닌 경우)
            if not inst_label:
                inst_consec = 0
                for d in inv_data:
                    if d.institution > 0:
                        inst_consec += 1
                    else:
                        break
                if inst_consec >= 3:
                    inst_label = str(inst_consec)
            if not frgn_label:
                frgn_consec = 0
                for d in inv_data:
                    if d.foreign > 0:
                        frgn_consec += 1
                    else:
                        break
                if frgn_consec >= 3:
                    frgn_label = str(frgn_consec)

        # 리포트(3거래일)/노다지(5거래일) 최근 자료 확인
        from datetime import timedelta
        today_date = today.date
        recent_reports = list(Report.objects.filter(stock=stock, date__gte=today_date - timedelta(days=5)).order_by('-date')[:3])
        has_report = bool(recent_reports)
        recent_nodajis = list(Nodaji.objects.filter(stock=stock, title__contains=stock.name, date__gte=today_date - timedelta(days=9)).order_by('-date')[:3])
        has_nodaji = bool(recent_nodajis)

        # 괴리율 (최신 리포트 목표가 vs 현재가)
        report_gap = None
        latest_report = Report.objects.filter(stock=stock, target_price__isnull=False).order_by('-date').first()
        if latest_report and latest_report.target_price and stock.current_price:
            report_gap = round((latest_report.target_price / stock.current_price - 1) * 100, 1)

        # 매수/매도 범위 판단
        in_buy_zone = False
        in_sell_zone = False
        if stock.current_price and stock.buy_price:
            in_buy_zone = stock.current_price <= stock.buy_price
        if stock.current_price and stock.sell_price:
            in_sell_zone = stock.current_price >= stock.sell_price

        _gc = _gongsi_map.get(stock.code)
        status_stocks.append({
            'stock': stock,
            'level': stock.interest_level,
            'vol_high_20': today_vol > 0 and today_vol >= max_vol_20,
            'vol_high_60': today_vol > 0 and today_vol >= max_vol_60,
            'is_bullish': today.closing_price >= today.opening_price if today.opening_price else True,
            'ma_align': ma_align,
            'pullback': pullback,
            'pullback_label': pullback_label,
            'has_report': has_report,
            'has_nodaji': has_nodaji,
            'report_gap': report_gap,
            'signal_info': signal_info,
            'sparkline': sparkline,
            'inst_label': inst_label,
            'frgn_label': frgn_label,
            'gongsi_cat': _gc[0] if _gc else '',
            'gongsi_title': _gc[1] if _gc else '',
            'in_buy_zone': in_buy_zone,
            'in_sell_zone': in_sell_zone,
            'recent_reports': recent_reports,
            'recent_nodajis': recent_nodajis,
            'inv_data': inv_data if signal_info else [],
            'short_data': list(ShortSelling.objects.filter(stock=stock).order_by('-date')[:20]) if signal_info else [],
        })
        # 알림 조건 판단
        _alerts = []
        if today_vol > 0 and today_vol >= max_vol_60:
            _alerts.append('거래량 60일 최대')
        elif today_vol > 0 and today_vol >= max_vol_20:
            _alerts.append('거래량 20일 최대')
        if pullback_label == '얕은눌림':
            _alerts.append(f'얕은눌림({pullback}%)')
        elif pullback_label == '깊은눌림':
            _alerts.append(f'깊은눌림({pullback}%)')
        if inst_label == '20일':
            _alerts.append('기관 20일 최대 매수')
        elif inst_label.isdigit() and int(inst_label) >= 5:
            _alerts.append(f'기관 {inst_label}일 연속 매수')
        if frgn_label == '20일':
            _alerts.append('외국인 20일 최대 매수')
        elif frgn_label.isdigit() and int(frgn_label) >= 5:
            _alerts.append(f'외국인 {frgn_label}일 연속 매수')
        if in_buy_zone:
            _alerts.append(f'매수 희망가 도달({stock.buy_price:,}원)')
        if in_sell_zone:
            _alerts.append(f'매도 희망가 도달({stock.sell_price:,}원)')
        status_stocks[-1]['has_alert'] = bool(_alerts)
        status_stocks[-1]['alert_conditions'] = ' / '.join(_alerts)
        status_stocks[-1]['recent_perf'] = _recent_perf_map.get(stock.code, '')

    # D-10 이내 이벤트 수집
    from datetime import date
    today = date.today()
    d10 = today + timedelta(days=10)
    upcoming_events = []
    for ev in StockEvent.objects.filter(date__gte=today, date__lte=d10).select_related('stock').order_by('date'):
        upcoming_events.append({'type': '종목', 'name': ev.stock.name, 'date': ev.date, 'date_text': ev.date_text, 'title': ev.title, 'content': ev.content, 'days_left': (ev.date - today).days, 'level': ev.stock.interest_level or ''})
    for ev in SectorEvent.objects.filter(date__gte=today, date__lte=d10).select_related('sector').order_by('date'):
        upcoming_events.append({'type': '섹터', 'name': ev.sector.name, 'date': ev.date, 'date_text': ev.date_text, 'title': ev.title, 'content': ev.content, 'days_left': (ev.date - today).days, 'level': 'all'})
    for ev in ETFEvent.objects.filter(date__gte=today, date__lte=d10).select_related('etf').order_by('date'):
        upcoming_events.append({'type': 'ETF', 'name': ev.etf.name, 'date': ev.date, 'date_text': ev.date_text, 'title': ev.title, 'content': ev.content, 'days_left': (ev.date - today).days, 'level': 'all'})
    upcoming_events.sort(key=lambda x: x['date'])

    from .models import SystemSetting
    prompt_status = SystemSetting.objects.filter(key='prompt_status').values_list('value', flat=True).first() or ''

    # 현황 데이터 블록 텍스트 생성 (레벨별)
    status_blocks_by_level = {'super': [], 'normal': [], 'waiting': []}
    for item in status_stocks:
        s = item['stock']
        lines = [f"종목명: {s.name}"]
        price_str = f"{s.current_price:,}" if s.current_price else '-'
        rate_str = f"{'+' if s.change_rate and s.change_rate > 0 else ''}{s.change_rate}%" if s.change_rate else ''
        lines.append(f"현재가: {price_str} ({rate_str})" if rate_str else f"현재가: {price_str}")
        align_map = {'bull': '정배열(▲)', 'bear': '역배열(▼)', 'mixed': '혼조(▬)'}
        lines.append(f"배열: {align_map.get(item['ma_align'], '-')}")
        if item['pullback_label']:
            lines.append(f"눌림목: {item['pullback_label']} (MA20 대비 {'+' if item['pullback'] > 0 else ''}{item['pullback']}%)")
        vol_parts = []
        if item.get('vol_high_60'):
            vol_parts.append(f"60일 최대 ({'양봉' if item.get('is_bullish') else '음봉'})")
        elif item.get('vol_high_20'):
            vol_parts.append(f"20일 최대 ({'양봉' if item.get('is_bullish') else '음봉'})")
        if vol_parts:
            lines.append(f"거래량: {', '.join(vol_parts)}")
        si = item.get('signal_info')
        if si:
            si_data = si if isinstance(si, dict) else {'signal_days_ago': si.get('signal_days_ago', 0), 'signal_price_change': si.get('signal_price_change', 0)} if hasattr(si, 'get') else None
            if si_data:
                days_ago = si_data.get('signal_days_ago', 0)
                pct = si_data.get('signal_price_change', 0)
                ago_str = f"{days_ago}일전 " if days_ago > 0 else ''
                lines.append(f"신호: {ago_str}{'+' if pct > 0 else ''}{pct}%")
        if item['inst_label']:
            label = '20일 최대 순매수' if item['inst_label'] == '20일' else f"{item['inst_label']}일 연속 순매수"
            lines.append(f"기관: {label}")
        if item['frgn_label']:
            label = '20일 최대 순매수' if item['frgn_label'] == '20일' else f"{item['frgn_label']}일 연속 순매수"
            lines.append(f"외국인: {label}")
        if item['gongsi_cat']:
            gongsi_str = f"공시: {item['gongsi_cat']}"
            if item.get('gongsi_title'):
                gongsi_str += f" — {item['gongsi_title']}"
            lines.append(gongsi_str)
        if item.get('recent_reports'):
            gap_str = f" (괴리율 {'+' if item['report_gap'] > 0 else ''}{item['report_gap']}%)" if item.get('report_gap') is not None else ''
            titles = ', '.join(r.title for r in item['recent_reports'] if r.title)
            lines.append(f"리포트: {titles}{gap_str}" if titles else f"리포트: 있음{gap_str}")
        elif item.get('report_gap') is not None:
            lines.append(f"괴리율: {'+' if item['report_gap'] > 0 else ''}{item['report_gap']}%")
        if item.get('recent_nodajis'):
            titles = ', '.join(n.title for n in item['recent_nodajis'] if n.title)
            lines.append(f"노다지: {titles}" if titles else "노다지: 있음")
        if item.get('in_buy_zone'):
            lines.append(f"매수구간: 도달 (매수가 {s.buy_price:,})")
        if item.get('in_sell_zone'):
            lines.append(f"매도구간: 도달 (매도가 {s.sell_price:,})")
        # 신호 종목: 수급/공매도 20일 데이터
        if item.get('inv_data'):
            inv_lines = ['  날짜 | 외국인 | 기관']
            for d in item['inv_data']:
                inv_lines.append(f"  {d.date.strftime('%Y-%m-%d')} | {d.foreign:,} | {d.institution:,}")
            lines.append("수급 20일:\n" + '\n'.join(inv_lines))
        if item.get('short_data'):
            short_lines = ['  날짜 | 공매도량 | 비중(%)']
            for d in item['short_data']:
                short_lines.append(f"  {d.date.strftime('%Y-%m-%d')} | {d.short_volume:,} | {d.trading_weight}%")
            lines.append("공매도 20일:\n" + '\n'.join(short_lines))
        level = item.get('level', 'normal')
        if level in status_blocks_by_level:
            status_blocks_by_level[level].append('\n'.join(lines))
    status_data_by_level = {k: '\n\n---\n\n'.join(v) for k, v in status_blocks_by_level.items()}

    context = {
        'super_stocks': super_stocks,
        'normal_stocks': normal_stocks,
        'waiting_stocks': waiting_stocks,
        'card_a_stocks': card_a_stocks,
        'card_a_down_stocks': card_a_down_stocks,
        'card_b_stocks': card_b_stocks,
        'card_b_down_stocks': card_b_down_stocks,
        'card_d_stocks': card_d_stocks,
        'card_c_stocks': card_c_stocks,
        'card_report_stocks': card_report_stocks,
        'card_nodaji_stocks': card_nodaji_stocks,
        'status_stocks': status_stocks,
        'upcoming_events': upcoming_events,
        'prompt_status': prompt_status,
        'status_data_by_level': status_data_by_level,
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
    from django.db.models import Q
    stock = get_object_or_404(Info.objects.prefetch_related('themes__category', 'custom_sectors'), code=code)

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

    # 컨센서스 테이블 데이터 (연간/분기: 매출액·영업이익·EPS·PER·PBR·ROE / 단위 억원)
    from .models import Consensus

    def _consensus_rows(rows):
        out = []
        for o in rows:
            out.append({
                'period': str(o.year) if not o.quarter else f"{o.year} {o.quarter}",
                'is_estimated': o.is_estimated,
                'revenue': float(o.revenue) if o.revenue is not None else None,
                'operating_profit': float(o.operating_profit) if o.operating_profit is not None else None,
                'eps': o.eps,
                'per': float(o.per) if o.per is not None else None,
                'pbr': float(o.pbr) if o.pbr is not None else None,
                'roe': float(o.roe) if o.roe is not None else None,
            })
        return out

    _cons_annual = list(Consensus.objects.filter(stock=stock, quarter__isnull=True).order_by('year'))
    _cons_quarter = list(Consensus.objects.filter(stock=stock, quarter__isnull=False).order_by('year', 'quarter'))
    consensus_annual_rows = _consensus_rows(_cons_annual)
    consensus_quarter_rows = _consensus_rows(_cons_quarter)
    has_consensus = bool(_cons_annual or _cons_quarter)

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

    ma10 = calc_ma(daily_charts, 10)
    ma20 = calc_ma(daily_charts, 20)
    ma60 = calc_ma(daily_charts, 60)

    # 이평선 최신값 (매매근거에서 사용)
    ma10_value = next((v for v in reversed(ma10) if v is not None), None)
    ma20_value = next((v for v in reversed(ma20) if v is not None), None)
    ma60_value = next((v for v in reversed(ma60) if v is not None), None)

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

    # 섹터 (업종) - 고유한 이름만 추출
    sectors = stock.sectors.values('code', 'name').distinct().order_by('name')

# 리포트 (최근 20개)
    reports_queryset = Report.objects.filter(stock=stock).order_by('-date')
    total_reports = reports_queryset.count()
    reports = list(reports_queryset[:20])

    # 리포트별 괴리율 계산 (목표가 vs 해당일 종가)
    if reports:
        report_dates = [r.date for r in reports if r.date]
        price_by_date = {
            dc.date: dc.closing_price
            for dc in DailyChart.objects.filter(stock=stock, date__in=report_dates)
        }
        for r in reports:
            if r.target_price and r.date in price_by_date:
                closing = price_by_date[r.date]
                r.gap_rate = round((r.target_price / closing - 1) * 100, 1)
            else:
                r.gap_rate = None

    # 노다지 (최근 20개)
    nodaji_queryset = Nodaji.objects.filter(
        stock=stock,
        title__contains=stock.name
    ).order_by('-date')
    total_nodaji = nodaji_queryset.count()
    nodaji_list = list(nodaji_queryset[:20])
    nodaji_summary_count = sum(1 for n in nodaji_list if n.summary)

    # 공시 (최근 20개) + 호재/악재/검토 분류
    _raw_gongsi = list(Gongsi.objects.filter(stock=stock).order_by('-date')[:20])
    for g in _raw_gongsi:
        g.cat = _classify_gongsi(g.title)
    gongsi_list = _raw_gongsi

    # 수급 (투자자별 매매동향, 최근 60일)
    investor_trends = list(InvestorTrend.objects.filter(stock=stock).order_by('-date')[:60])

    # 수급 누적 차트 데이터 - 키움 (오래된 날짜부터)
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

    # 수급 데이터 - 다음 (daum_foreign, daum_institution이 있는 것만)
    investor_trends_daum_raw = [t for t in investor_trends if t.daum_foreign is not None or t.daum_institution is not None]

    # DailyChart에서 주가/등락률/거래량 가져오기
    daum_dates = [t.date for t in investor_trends_daum_raw]
    daily_charts_map = {
        dc.date: dc for dc in DailyChart.objects.filter(stock=stock, date__in=daum_dates)
    }

    # 다음 탭용 데이터에 주가 정보 추가
    investor_trends_daum = []
    for t in investor_trends_daum_raw:
        dc = daily_charts_map.get(t.date)
        t.closing_price = dc.closing_price if dc else None
        t.price_change = dc.price_change if dc else None
        t.trading_volume = dc.trading_volume if dc else None
        # 등락률 계산
        if dc and dc.closing_price and dc.price_change:
            prev_price = dc.closing_price - dc.price_change
            t.change_rate = round((dc.price_change / prev_price) * 100, 2) if prev_price else 0
        else:
            t.change_rate = None
        investor_trends_daum.append(t)

    # 수급 누적 차트 데이터 - 다음 (주가 포함)
    investor_chart_data_daum = []
    if investor_trends_daum:
        trends_daum_asc = list(reversed(investor_trends_daum))
        cum_daum_foreign = 0
        cum_daum_institution = 0
        for t in trends_daum_asc:
            cum_daum_foreign += t.daum_foreign or 0
            cum_daum_institution += t.daum_institution or 0
            investor_chart_data_daum.append({
                'date': t.date.strftime('%m.%d'),
                'foreign': cum_daum_foreign,
                'institution': cum_daum_institution,
                'price': t.closing_price,
            })

    # 공매도 (최근 60일)
    short_sellings = ShortSelling.objects.filter(stock=stock).order_by('-date')[:60]

    # ========== 수급 대시보드 계산 ==========
    supply_dashboard = None
    supply_dashboard_chart = []
    supply_dashboard_reason = ''
    shorts_list = list(short_sellings)
    daum_count = len(investor_trends_daum)
    short_count = len(shorts_list)
    min_days = 20
    if daum_count < min_days or short_count < min_days:
        reasons = []
        if daum_count < min_days:
            reasons.append(f'수급 데이터 {daum_count}/{min_days}일')
        if short_count < min_days:
            reasons.append(f'공매도 데이터 {short_count}/{min_days}일')
        supply_dashboard_reason = '데이터 부족: ' + ', '.join(reasons)
    if daum_count >= min_days and short_count >= min_days:
        import statistics
        trends_asc = sorted(investor_trends_daum, key=lambda t: t.date)
        shorts_asc = sorted(shorts_list, key=lambda s: s.date)
        # 사용할 윈도우: 최대 60일, 있는 만큼
        window = min(60, daum_count, short_count)

        latest = trends_asc[-1]
        latest_dc = daily_charts_map.get(latest.date)
        current_price = latest_dc.closing_price if latest_dc else (stock.current_price or 0)
        today_volume = latest_dc.trading_volume if latest_dc else 0

        # 외국인/기관 누적
        foreign_cum = sum(t.daum_foreign or 0 for t in trends_asc[-window:])
        inst_cum = sum(t.daum_institution or 0 for t in trends_asc[-window:])

        # 공매도 비중
        short_weights = [float(s.trading_weight or 0) for s in shorts_asc[-window:]]
        short_avg = statistics.mean(short_weights) if short_weights else 0
        short_std = statistics.stdev(short_weights) if len(short_weights) > 1 else 1
        today_short_weight = short_weights[-1] if short_weights else 0
        z_score = round((today_short_weight - short_avg) / short_std, 2) if short_std > 0 else 0

        # 숏 손익률 (short_trading_value는 천원 단위이므로 ×1000)
        cum_short_value = sum((s.short_trading_value or 0) * 1000 for s in shorts_asc[-window:])
        cum_short_vol = sum(s.short_volume or 0 for s in shorts_asc[-window:])
        short_avg_price = cum_short_value / cum_short_vol if cum_short_vol > 0 else 0
        short_pnl = round((current_price - short_avg_price) / short_avg_price * 100, 1) if short_avg_price > 0 else 0

        # C1: 수급 모멘텀
        recent_5 = sum((t.daum_foreign or 0) + (t.daum_institution or 0) for t in trends_asc[-5:])
        daily_avg = sum((t.daum_foreign or 0) + (t.daum_institution or 0) for t in trends_asc[-window:]) / window
        c1 = (recent_5 / 5) / daily_avg * 100 if daily_avg != 0 else 0
        c1 = max(-100, min(100, c1))

        # C2: 공매도 Z-score 부호 반전
        c2 = -z_score * 50
        c2 = max(-100, min(100, c2))

        # C3: 숏 손익률 정규화
        c3 = short_pnl * 10
        c3 = max(-100, min(100, c3))

        # C4: 수급 강도
        today_net = (latest.daum_foreign or 0) + (latest.daum_institution or 0)
        c4 = (today_net / today_volume * 100 * 3) if today_volume > 0 else 0
        c4 = max(-100, min(100, c4))

        total_score = round(0.3 * c1 + 0.3 * c2 + 0.2 * c3 + 0.2 * c4, 1)

        supply_dashboard = {
            'score': total_score,
            'foreign_cum': foreign_cum,
            'inst_cum': inst_cum,
            'short_weight': round(today_short_weight, 1),
            'z_score': z_score,
            'short_pnl': short_pnl,
            'short_avg_price': round(short_avg_price),
            'window': window,
        }

        # 일별 차트 데이터
        shorts_date_map = {s.date: s for s in shorts_asc}
        for t in trends_asc[-window:]:
            s = shorts_date_map.get(t.date)
            supply_dashboard_chart.append({
                'label': t.date.strftime('%m.%d'),
                'foreign': t.daum_foreign or 0,
                'institution': t.daum_institution or 0,
                'short_weight': float(s.trading_weight or 0) if s else 0,
            })

    # 저장된 뉴스 (게시일 최신순)
    from .models import News
    def parse_news_date_detail(news):
        try:
            pub = (news.published or '').strip()
            date_part = pub.split(' ')[0] if pub else ''
            if date_part:
                parts = date_part.split('-')
                if len(parts) == 3:
                    return (int(parts[0]), int(parts[1]), int(parts[2]))
            return (0, 0, 0)
        except:
            return (0, 0, 0)
    news_articles = sorted(News.objects.filter(stock=stock), key=parse_news_date_detail, reverse=True)

    # 저장된 텔레그램 메시지 (최신순)
    from .models import TelegramMessage, Schedule
    telegram_messages = TelegramMessage.objects.filter(stock=stock).order_by('-date', '-time')

    # 뉴스 프롬프트용 변수 (향후 이벤트 포함)
    from datetime import date as _date
    from django.db.models import Q as _Q
    _today = _date.today()
    upcoming_schedules = Schedule.objects.filter(stock=stock).filter(
        _Q(date_sort__gte=_today) | _Q(date_sort__isnull=True)
    ).order_by('date_sort')
    future_events_text = '\n'.join(
        f"- {s.date_text}: {s.content}" for s in upcoming_schedules
    )
    news_prompt_vars = {
        'stock_name': stock.name,
        'stock_code': stock.code,
        'sector_name': '',
        'key_briefing': stock.key_briefing or '',
        'financial_analysis': stock.financial_analysis_v2 or '',
        'consensus_analysis': stock.consensus_analysis or '',
        'future_events': future_events_text,
    }

    # 질문리포트
    from .models import StockQuestionReport, ResearchPrompt, QuickReport, SummaryReport, WaitingReport
    question_reports = list(StockQuestionReport.objects.filter(stock=stock).order_by('-created_at'))

    # 기업분석 / 업데이트 / 대기 프롬프트
    research_prompts = ResearchPrompt.objects.all()
    quick_prompts = QuickReport.objects.all()
    summary_prompts = SummaryReport.objects.all()
    waiting_prompts = WaitingReport.objects.all()
    common_question_set = set(research_prompts.values_list('question', flat=True))
    update_question_set = set(quick_prompts.values_list('question', flat=True)) | set(summary_prompts.values_list('question', flat=True))
    waiting_question_set = set(waiting_prompts.values_list('question', flat=True))

    # 기업분석 / 업데이트 / 대기 / 개별 분리 (기업분석 우선)
    common_core_questions = {'사업모델', '수익구조', '중장기전망', '지배구조', '경쟁력', '경쟁사'}
    update_extra_questions = {'트래커', '매매대응'}
    common_core_reports = []
    common_extra_reports = []
    update_core_reports = []
    update_extra_reports = []
    waiting_question_reports = []
    custom_question_reports = []
    for qr in question_reports:
        if qr.question in common_question_set:
            if qr.question in common_core_questions:
                common_core_reports.append(qr)
            else:
                common_extra_reports.append(qr)
        elif qr.question in update_question_set:
            if qr.question in update_extra_questions:
                update_extra_reports.append(qr)
            else:
                update_core_reports.append(qr)
        elif qr.question in waiting_question_set:
            waiting_question_reports.append(qr)
        else:
            custom_question_reports.append(qr)
    # 일반 질문: 트래킹 먼저, 그 안에서 수정일 최신순
    custom_question_reports.sort(key=lambda q: (not q.is_tracking, -q.updated_at.timestamp()))
    # 기업분석 순서 고정
    common_order = ['사업모델', '수익구조', '경쟁력', '경쟁사', '중장기전망', '지배구조', '수주잔고', '파이프라인', 'R&D', '매장점포', '원자재공급망', '보유자산']
    common_core_reports.sort(key=lambda q: common_order.index(q.question) if q.question in common_order else 99)
    common_extra_reports.sort(key=lambda q: common_order.index(q.question) if q.question in common_order else 99)
    # 업데이트 순서 고정
    update_order = ['실적확인', '단기이슈', '중기이슈', '이벤트', '업황', '밸류확인', '트래커', '매매대응']
    update_core_reports.sort(key=lambda q: update_order.index(q.question) if q.question in update_order else 99)
    update_extra_reports.sort(key=lambda q: update_order.index(q.question) if q.question in update_order else 99)
    # 대기 순서 고정
    waiting_order = ['대기', '옥석가리기', '회사스냅샷', '매매매력도', '매매트래킹']
    waiting_question_reports.sort(key=lambda q: waiting_order.index(q.question) if q.question in waiting_order else 99)

    # 전체내용 생성 (DB에 있는 모든 분석 데이터)
    from .models import YoutubeVideo
    all_content_sections = []

    # 주가 통계
    if daily_charts:
        closes = [d.closing_price for d in daily_charts]
        volumes = [d.trading_volume for d in daily_charts]
        cur = closes[-1]

        # 52주(약 250일) 고저
        high_52w = max(closes)
        low_52w = min(closes)

        # 이동평균 대비
        def _ma_pct(ma_val):
            if ma_val and ma_val > 0:
                return f"{ma_val:,} ({'+' if cur >= ma_val else ''}{round((cur - ma_val) / ma_val * 100, 1)}%)"
            return '-'

        # MA120
        ma120_value = round(sum(closes[-120:]) / min(120, len(closes))) if len(closes) >= 120 else None

        # 거래량 분석
        vol_20 = round(sum(volumes[-20:]) / min(20, len(volumes))) if len(volumes) >= 20 else None
        vol_5 = round(sum(volumes[-5:]) / min(5, len(volumes))) if len(volumes) >= 5 else None
        vol_ratio = f"{'+' if vol_5 >= vol_20 else ''}{round((vol_5 - vol_20) / vol_20 * 100, 1)}%" if vol_20 and vol_5 and vol_20 > 0 else '-'

        # RSI(14)
        rsi_val = None
        if len(closes) >= 15:
            gains, losses = [], []
            for i in range(-14, 0):
                diff = closes[i] - closes[i - 1]
                gains.append(max(diff, 0))
                losses.append(max(-diff, 0))
            avg_gain = sum(gains) / 14
            avg_loss = sum(losses) / 14
            if avg_loss > 0:
                rs = avg_gain / avg_loss
                rsi_val = round(100 - (100 / (1 + rs)), 1)
            else:
                rsi_val = 100.0

        # MACD (12, 26, 9)
        macd_line = macd_signal = macd_hist = None
        if len(closes) >= 35:
            def _ema(data, period):
                k = 2 / (period + 1)
                ema = [data[0]]
                for p in data[1:]:
                    ema.append(p * k + ema[-1] * (1 - k))
                return ema
            ema12 = _ema(closes, 12)
            ema26 = _ema(closes, 26)
            macd_series = [e12 - e26 for e12, e26 in zip(ema12, ema26)]
            signal_series = _ema(macd_series[25:], 9) if len(macd_series) > 25 else []
            if signal_series:
                macd_line = round(macd_series[-1])
                macd_signal = round(signal_series[-1])
                macd_hist = round(macd_line - macd_signal)

        # 볼린저 밴드 (20일)
        bb_upper = bb_lower = bb_width = None
        if len(closes) >= 20:
            import statistics
            bb_mean = sum(closes[-20:]) / 20
            bb_std = statistics.stdev(closes[-20:])
            bb_upper = round(bb_mean + 2 * bb_std)
            bb_lower = round(bb_mean - 2 * bb_std)
            bb_width = round((bb_upper - bb_lower) / bb_mean * 100, 1)

        # 최근 변동성 (20일 일간 수익률 표준편차)
        volatility = None
        if len(closes) >= 21:
            daily_returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(-20, 0)]
            volatility = round(statistics.stdev(daily_returns) * 100, 2)

        price_lines = [
            f"현재가: {cur:,} | 52주 고가: {high_52w:,} (고점 대비 {round((cur - high_52w) / high_52w * 100, 1)}%) | 52주 저가: {low_52w:,} (저점 대비 +{round((cur - low_52w) / low_52w * 100, 1)}%)",
            f"MA10: {_ma_pct(ma10_value)} | MA20: {_ma_pct(ma20_value)} | MA60: {_ma_pct(ma60_value)} | MA120: {_ma_pct(ma120_value)}",
            f"거래량 20일평균: {vol_20:,} | 최근5일평균: {vol_5:,} (평균 대비 {vol_ratio})" if vol_20 and vol_5 else None,
        ]
        if rsi_val is not None:
            price_lines.append(f"RSI(14): {rsi_val}")
        if macd_line is not None:
            price_lines.append(f"MACD: {macd_line:,} | Signal: {macd_signal:,} | Histogram: {'+' if macd_hist >= 0 else ''}{macd_hist:,}")
        if bb_upper is not None:
            price_lines.append(f"볼린저밴드(20): 상단 {bb_upper:,} | 하단 {bb_lower:,} | 밴드폭 {bb_width}%")
        if volatility is not None:
            price_lines.append(f"20일 변동성: {volatility}% (일간)")

        all_content_sections.append("## 주가 통계\n" + '\n'.join(l for l in price_lines if l))
    # 기업분석
    for r in common_core_reports + common_extra_reports:
        if r.report:
            all_content_sections.append(f"## 기업분석: {r.question} ({r.updated_at.strftime('%Y-%m-%d')})\n{r.report}")
    # 업데이트
    for r in update_core_reports + update_extra_reports:
        if r.report:
            all_content_sections.append(f"## 업데이트: {r.question} ({r.updated_at.strftime('%Y-%m-%d')})\n{r.report}")
    # 대기
    for r in waiting_question_reports:
        if r.report:
            all_content_sections.append(f"## 대기: {r.question} ({r.updated_at.strftime('%Y-%m-%d')})\n{r.report}")
    # 일반 질문
    for r in custom_question_reports:
        if r.report:
            all_content_sections.append(f"## 일반: {r.question} ({r.updated_at.strftime('%Y-%m-%d')})\n{r.report}")
    # 핵심브리핑
    if stock.key_briefing:
        kb_date = stock.key_briefing_updated_at.strftime('%Y-%m-%d') if stock.key_briefing_updated_at else ''
        all_content_sections.append(f"## 핵심브리핑 ({kb_date})\n{stock.key_briefing}")
    # 재무분석
    if stock.financial_analysis_v2:
        fa_date = stock.financial_analysis_v2_updated_at.strftime('%Y-%m-%d') if stock.financial_analysis_v2_updated_at else ''
        all_content_sections.append(f"## 재무분석 ({fa_date})\n{stock.financial_analysis_v2}")
    # 컨센서스분석
    if stock.consensus_analysis:
        ca_date = stock.consensus_analysis_updated_at.strftime('%Y-%m-%d') if stock.consensus_analysis_updated_at else ''
        all_content_sections.append(f"## 컨센서스분석 ({ca_date})\n{stock.consensus_analysis}")
    # 수급 (날 데이터)
    if investor_trends_daum:
        sd_lines = ['날짜 | 종가 | 등락률 | 외국인 | 기관 | 거래량']
        for t in investor_trends_daum:
            price_str = f"{t.closing_price:,}" if t.closing_price else '-'
            rate_str = f"{'+' if t.change_rate and t.change_rate > 0 else ''}{t.change_rate}%" if t.change_rate is not None else '-'
            sd_lines.append(f"{t.date.strftime('%Y-%m-%d')} | {price_str} | {rate_str} | {t.daum_foreign or 0} | {t.daum_institution or 0} | {t.trading_volume or 0}")
        all_content_sections.append("## 수급 데이터\n" + '\n'.join(sd_lines))
    # 수급분석 (AI 분석 결과)
    if stock.supply_demand_analysis:
        sd_date = stock.supply_demand_analysis_updated_at.strftime('%Y-%m-%d') if stock.supply_demand_analysis_updated_at else ''
        all_content_sections.append(f"## 수급분석 ({sd_date})\n{stock.supply_demand_analysis}")
    # 공시
    if gongsi_list:
        gongsi_parts = []
        for g in gongsi_list:
            cat = getattr(g, 'cat', '')
            cat_str = f" [{cat}]" if cat else ''
            gongsi_parts.append(f"[{g.date.strftime('%Y-%m-%d') if g.date else ''}]{cat_str} {g.title}")
        all_content_sections.append("## 공시\n" + '\n'.join(gongsi_parts))
    # 리포트 (목표가 포함, 요약 있으면 요약도)
    if reports:
        report_parts = []
        for r in reports:
            date_str = r.date.strftime('%Y-%m-%d') if r.date else ''
            price_str = f" 목표가:{r.target_price:,}" if r.target_price else ''
            opinion_str = f" ({r.recommendation})" if r.recommendation else ''
            line = f"[{date_str}] {r.provider} - {r.title}{price_str}{opinion_str}"
            if r.summary:
                line += f"\n{r.summary}"
            report_parts.append(line)
        all_content_sections.append("## 리포트\n" + '\n\n'.join(report_parts))
    # 뉴스 (요약이 있는 것만)
    news_parts = []
    for n in news_articles:
        if n.summary or n.my_opinion:
            title = f"[{n.published or ''}] {n.title or ''}"
            content = n.my_opinion or n.summary
            news_parts.append(f"{title}\n{content}")
    if news_parts:
        all_content_sections.append("## 뉴스\n" + '\n\n'.join(news_parts))
    # 노다지 (요약이 있는 것만)
    nodaji_parts = []
    for n in nodaji_list:
        if n.summary:
            nodaji_parts.append(f"[{n.date.strftime('%Y-%m-%d') if n.date else ''}] {n.title}\n{n.summary}")
    if nodaji_parts:
        all_content_sections.append("## 노다지\n" + '\n\n'.join(nodaji_parts))
    # 유튜브 (요약이 있는 것만)
    youtube_videos = YoutubeVideo.objects.filter(stock=stock).order_by('-id')
    yt_parts = []
    for v in youtube_videos:
        if v.summary:
            yt_parts.append(f"[{v.published or ''}] {v.channel} - {v.title}\n{v.summary}")
    if yt_parts:
        all_content_sections.append("## 유튜브\n" + '\n\n'.join(yt_parts))
    # 향후 이벤트
    if future_events_text:
        all_content_sections.append(f"## 향후 이벤트\n{future_events_text}")
    news_prompt_vars['all_content'] = '\n\n---\n\n'.join(all_content_sections) if all_content_sections else ''

    # 업로드 리포트
    from .models import StockUploadedReport, SystemSetting
    uploaded_reports = StockUploadedReport.objects.filter(stock=stock).order_by('-created_at')

    # 리포트 요약 개수 (애널리스트 리포트 + 파일 리포트)
    report_summary_count = sum(1 for r in reports if r.summary)
    report_attachment_count = sum(1 for r in reports if not r.summary and r.has_attachment)
    uploaded_summary_count = sum(1 for r in uploaded_reports if r.summary)
    uploaded_attachment_count = sum(1 for r in uploaded_reports if not r.summary and r.has_attachment)
    total_summary_count = report_summary_count + uploaded_summary_count
    total_attachment_count = report_attachment_count + uploaded_attachment_count

    # 거래량 변동률 계산 (전일 대비)
    volume_change_rate = None
    if len(daily_charts) >= 2:
        today_volume = daily_charts[-1].trading_volume
        prev_volume = daily_charts[-2].trading_volume
        if prev_volume and prev_volume > 0:
            volume_change_rate = round((today_volume - prev_volume) / prev_volume * 100, 1)

    # 최근 5거래일 기준 리포트/노다지/공시 존재 여부
    recent_5_dates = [d.date for d in daily_charts[-5:]] if len(daily_charts) >= 5 else [d.date for d in daily_charts]
    has_recent_report = any(r.date in recent_5_dates for r in reports if r.date)
    has_recent_nodaji = any(n.date in recent_5_dates for n in nodaji_list if n.date)
    has_recent_gongsi = any(g.date in recent_5_dates for g in gongsi_list if g.date)

    # 최근 수급 (다음 기준, 외국인/기관)
    latest_investor = None
    if investor_trends_daum:
        latest_investor = {
            'date': investor_trends_daum[0].date,
            'foreign': investor_trends_daum[0].daum_foreign,
            'institution': investor_trends_daum[0].daum_institution,
        }

    # 최근 공매도 비중
    latest_short = None
    if short_sellings:
        latest_short = {
            'date': short_sellings[0].date,
            'weight': short_sellings[0].trading_weight,
        }

    # 최근 리포트 괴리율 (값이 있는 가장 최근 리포트)
    latest_report_gap = None
    latest_report_gap_date = None
    for r in reports:
        if hasattr(r, 'gap_rate') and r.gap_rate is not None:
            latest_report_gap = r.gap_rate
            latest_report_gap_date = r.date
            break

    # 3개월 평균 목표주가 (컨센서스 프롬프트용)
    from datetime import timedelta
    three_months_ago = _today - timedelta(days=90)
    recent_target_prices = Report.objects.filter(
        stock=stock, date__gte=three_months_ago, target_price__isnull=False
    ).values_list('target_price', flat=True)
    avg_target_price_3m = round(sum(recent_target_prices) / len(recent_target_prices)) if recent_target_prices else None

    # 주가 vs 목표가 차트 데이터 (리포트 탭용)
    price_chart_data = []
    target_chart_data = []
    gap_chart_data = []
    if reports:
        # 리포트 목표가와 해당 날짜의 종가 데이터
        report_dates = [r.date for r in reports if r.date]
        daily_price_map = {
            dc.date: dc.closing_price
            for dc in DailyChart.objects.filter(stock=stock, date__in=report_dates)
        }
        for r in reversed(reports):
            if r.date and r.target_price:
                date_str = r.date.strftime('%Y-%m-%d')
                closing = daily_price_map.get(r.date)
                if closing:
                    price_chart_data.append({'x': date_str, 'y': closing})
                    target_chart_data.append({'x': date_str, 'y': r.target_price})
                    gap = round((r.target_price - closing) / closing * 100, 1)
                    gap_chart_data.append({'x': date_str, 'y': gap})

    # 보유 손익률 (평단가 대비 현재가) - 렌더링 시점 즉석 계산, DB 저장 안 함
    # current_price는 데일리 배치(save_stock_info)가 매일 갱신하므로 별도 재계산 불필요
    holding_return = None
    if stock.avg_buy_price and stock.current_price:
        holding_return = round((stock.current_price - stock.avg_buy_price) / stock.avg_buy_price * 100, 1)

    context = {
        'stock': stock,
        'holding_return': holding_return,
        'sectors': sectors,
        'volume_change_rate': volume_change_rate,
        'has_recent_report': has_recent_report,
        'has_recent_nodaji': has_recent_nodaji,
        'has_recent_gongsi': has_recent_gongsi,
        'latest_investor': latest_investor,
        'latest_short': latest_short,
        'latest_report_gap': latest_report_gap,
        'latest_report_gap_date': latest_report_gap_date,
        'annual_labels': json.dumps(annual_labels),
        'annual_revenue': json.dumps(annual_revenue),
        'annual_op': json.dumps(annual_op),
        'annual_estimated': json.dumps(annual_estimated),
        'quarterly_labels': json.dumps(quarterly_labels),
        'quarterly_revenue': json.dumps(quarterly_revenue),
        'quarterly_op': json.dumps(quarterly_op),
        'quarterly_estimated': json.dumps(quarterly_estimated),
        'has_consensus': has_consensus,
        'consensus_annual_rows': json.dumps(consensus_annual_rows),
        'consensus_quarter_rows': json.dumps(consensus_quarter_rows),
        'daily_candle_data': json.dumps(daily_candle_data),
        'daily_volume_data': json.dumps(daily_volume_data),
        'daily_ma20_data': json.dumps(daily_ma20_data),
        'daily_ma60_data': json.dumps(daily_ma60_data),
        'weekly_candle_data': json.dumps(weekly_candle_data),
        'weekly_volume_data': json.dumps(weekly_volume_data),
        'monthly_candle_data': json.dumps(monthly_candle_data),
        'monthly_volume_data': json.dumps(monthly_volume_data),
        # 탭 데이터
        'reports': reports,
        'total_reports': total_reports,
        'nodaji_list': nodaji_list,
        'total_nodaji': total_nodaji,
        'nodaji_summary_count': nodaji_summary_count,
        'gongsi_list': gongsi_list,
        'investor_trends': investor_trends,
        'investor_chart_data': json.dumps(investor_chart_data),
        'investor_trends_daum': investor_trends_daum,
        'investor_chart_data_daum': json.dumps(investor_chart_data_daum),
        'supply_demand_prompt_data': json.dumps([{
            'date': t.date.strftime('%Y-%m-%d'),
            'foreign': t.daum_foreign or 0,
            'institution': t.daum_institution or 0,
            'volume': t.trading_volume or 0,
        } for t in investor_trends_daum]),
        'short_selling_prompt_data': json.dumps([{
            'date': s.date.strftime('%Y-%m-%d'),
            'short_volume': s.short_volume,
            'trading_weight': float(s.trading_weight),
            'short_trading_value': s.short_trading_value,
            'short_average_price': s.short_average_price,
        } for s in short_sellings]),
        'short_sellings': short_sellings,
        'supply_dashboard': supply_dashboard,
        'supply_dashboard_chart': json.dumps(supply_dashboard_chart),
        'supply_dashboard_reason': supply_dashboard_reason,
        'news_articles': news_articles,
        'telegram_messages': telegram_messages,
        'question_reports': question_reports,
        'common_core_reports': common_core_reports,
        'common_extra_reports': common_extra_reports,
        'update_core_reports': update_core_reports,
        'update_extra_reports': update_extra_reports,
        'waiting_question_reports': waiting_question_reports,
        'custom_question_reports': custom_question_reports,
        'research_prompts': research_prompts,
        'uploaded_reports': uploaded_reports,
        'total_summary_count': total_summary_count,
        'total_attachment_count': total_attachment_count,
        'price_chart_data': json.dumps(price_chart_data),
        'target_chart_data': json.dumps(target_chart_data),
        'gap_chart_data': json.dumps(gap_chart_data),
        'saved_prompts': {s.key: s.value for s in SystemSetting.objects.filter(key__startswith='prompt_')},
        'news_prompt_vars': news_prompt_vars,
        'ma10_value': ma10_value,
        'ma20_value': ma20_value,
        'ma60_value': ma60_value,
        'briefing_data': _build_briefing_data(stock, question_reports, nodaji_list, reports, common_core_reports + common_extra_reports, update_core_reports + update_extra_reports),
        'avg_target_price_3m': avg_target_price_3m,
        'diary_trades_json': json.dumps([
            {'date': d.date.strftime('%Y-%m-%d'), 'is_buy': d.is_buy, 'is_sell': d.is_sell}
            for d in StockDiary.objects.filter(stock=stock).filter(Q(is_buy=True) | Q(is_sell=True)).only('date', 'is_buy', 'is_sell')
        ]),
    }
    return render(request, 'stocks/stock_detail.html', context)


def _build_briefing_data(stock, question_reports, nodaji_list, reports, common_question_reports=None, update_question_reports=None):
    """핵심브리핑 프롬프트용 데이터 구성"""
    try:
        from .models import IncomeStatement

        data = {}

        # {전체내용} 데이터: 기업분석 + 업데이트 리서치
        all_content_sections = []
        if common_question_reports:
            for r in common_question_reports:
                if r.report:
                    all_content_sections.append(f"## 기업분석: {r.question} ({r.updated_at.strftime('%Y-%m-%d')})\n{r.report}")
        if update_question_reports:
            for r in update_question_reports:
                if r.report:
                    all_content_sections.append(f"## 업데이트: {r.question} ({r.updated_at.strftime('%Y-%m-%d')})\n{r.report}")
        data['all_content'] = '\n\n---\n\n'.join(all_content_sections) if all_content_sections else ''

        # 기업분석기준분기: 포괄손익계산서 최신 비추정 분기
        latest_quarters = IncomeStatement.objects.filter(
            stock=stock, quarter__isnull=False
        ).order_by('-year', '-quarter')
        base_quarter = ''
        for q in latest_quarters:
            if not q.is_estimated:
                base_quarter = f"{q.year}/{q.quarter}"
                break
        data['base_quarter'] = base_quarter

        # 재무분석, 컨센서스분석 (모델 필드)
        data['financial_analysis'] = stock.financial_analysis_v2 or ''
        data['consensus_analysis'] = stock.consensus_analysis or ''

        # 리서치 기반 분석 (질문명으로 매칭)
        qr_map = {}
        for qr in question_reports:
            qr_map[qr.question] = qr.report or ''

        data['valuation_analysis'] = qr_map.get('밸류에이션', '')
        data['macro_analysis'] = qr_map.get('업황/매크로', '')
        data['event_analysis'] = qr_map.get('향후 이벤트', '')
        data['competitor_analysis'] = qr_map.get('경쟁사', '')

        # 노다지 요약
        parts = []
        for n in nodaji_list[:5]:
            if n.summary:
                parts.append(f"[{n.date.strftime('%Y-%m-%d') if n.date else '-'}] {n.title}\n{n.summary}")
        data['nodaji'] = '\n\n---\n\n'.join(parts)

        # 리포트 요약
        report_parts = []
        for r in reports[:10]:
            if r.summary:
                date_str = r.date.strftime('%Y-%m-%d') if r.date else '-'
                report_parts.append(f"[{date_str}] {r.provider or ''} - {r.title or ''}\n{r.summary}")
        data['report_summary'] = '\n\n---\n\n'.join(report_parts)

        return data
    except Exception:
        return {}


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
                logger.info(f'[FAV] {stock_code} save_investor_daum 시작')
                call_command('save_investor_daum', code=stock_code, mode='all')
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
        stock.is_tracking = request.POST.get('is_tracking') == 'on'

        # 매수가(평단가): 입력되면 보유중 자동 체크, 비우면 해제
        _avg_buy_raw = request.POST.get('avg_buy_price', '').replace(',', '').strip()
        if _avg_buy_raw:
            try:
                stock.avg_buy_price = int(float(_avg_buy_raw))
                stock.is_holding = True
            except ValueError:
                pass
        else:
            stock.avg_buy_price = None

        stock.save()

        # 업종 저장 (ManyToMany)
        from .models import Theme
        theme_ids = request.POST.getlist('themes')
        stock.themes.set(Theme.objects.filter(id__in=theme_ids))

        # 관심섹터 저장 (ManyToMany)
        from .models import CustomSector
        sector_ids = request.POST.getlist('custom_sectors')
        stock.custom_sectors.set(CustomSector.objects.filter(id__in=sector_ids))

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

    # 공시 (최근 20개) + 호재/악재/검토 분류
    _raw_gongsi2 = list(Gongsi.objects.filter(stock=stock).order_by('-date')[:20])
    for g in _raw_gongsi2:
        g.cat = _classify_gongsi(g.title)
    gongsi_list = _raw_gongsi2

    # 수급 (투자자별 매매동향, 최근 60일)
    investor_trends = list(InvestorTrend.objects.filter(stock=stock).order_by('-date')[:60])

    # 수급 누적 차트 데이터 - 키움 (오래된 날짜부터)
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

    # 수급 데이터 - 다음 (daum_foreign, daum_institution이 있는 것만)
    investor_trends_daum_raw = [t for t in investor_trends if t.daum_foreign is not None or t.daum_institution is not None]

    # DailyChart에서 주가/등락률/거래량 가져오기
    daum_dates = [t.date for t in investor_trends_daum_raw]
    daily_charts = {
        dc.date: dc for dc in DailyChart.objects.filter(stock=stock, date__in=daum_dates)
    }

    # 다음 탭용 데이터에 주가 정보 추가
    investor_trends_daum = []
    for t in investor_trends_daum_raw:
        dc = daily_charts.get(t.date)
        t.closing_price = dc.closing_price if dc else None
        t.price_change = dc.price_change if dc else None
        t.trading_volume = dc.trading_volume if dc else None
        # 등락률 계산
        if dc and dc.closing_price and dc.price_change:
            prev_price = dc.closing_price - dc.price_change
            t.change_rate = round((dc.price_change / prev_price) * 100, 2) if prev_price else 0
        else:
            t.change_rate = None
        investor_trends_daum.append(t)

    # 수급 누적 차트 데이터 - 다음 (주가 포함)
    investor_chart_data_daum = []
    if investor_trends_daum:
        trends_daum_asc = list(reversed(investor_trends_daum))
        cum_daum_foreign = 0
        cum_daum_institution = 0
        for t in trends_daum_asc:
            cum_daum_foreign += t.daum_foreign or 0
            cum_daum_institution += t.daum_institution or 0
            investor_chart_data_daum.append({
                'date': t.date.strftime('%m.%d'),
                'foreign': cum_daum_foreign,
                'institution': cum_daum_institution,
                'price': t.closing_price,
            })

    # 공매도 (최근 60일)
    short_sellings = ShortSelling.objects.filter(stock=stock).order_by('-date')[:60]

    # 관심섹터 (전체)
    from .models import CustomSector
    custom_sectors = CustomSector.objects.all()

    # 종목분류 프롬프트 (설정에서 가져오기)
    from .models import SystemSetting
    classify_prompt = SystemSetting.objects.filter(key='prompt_classify').values_list('value', flat=True).first() or ''

    # 종목분류 현황 (현재 DB에 저장된 모든 종목 분류 - "종목명 | 대분류 | 중분류")
    classify_lines = []
    stocks_with_themes = Info.objects.filter(themes__isnull=False).prefetch_related('themes__category').distinct()
    for s in stocks_with_themes:
        for t in s.themes.all():
            classify_lines.append(f"{s.name} | {t.category.name} | {t.name}")
    classify_status_text = '\n'.join(classify_lines)

    context = {
        'stock': stock,
        'interest_choices': interest_choices,
        'custom_sectors': custom_sectors,
        'classify_prompt': classify_prompt,
        'classify_status_text': classify_status_text,
        'gongsi_list': gongsi_list,
        'investor_trends': investor_trends,
        'investor_chart_data': json.dumps(investor_chart_data),
        'investor_trends_daum': investor_trends_daum,
        'investor_chart_data_daum': json.dumps(investor_chart_data_daum),
        'short_sellings': short_sellings,
    }
    return render(request, 'stocks/stock_edit.html', context)


from django.views.decorators.clickjacking import xframe_options_sameorigin



@xframe_options_sameorigin
def stock_insight_summary_html(request, code):
    """인사이트 요약 HTML 페이지"""
    from django.http import HttpResponse, Http404
    stock = get_object_or_404(Info, code=code)
    if not stock.insight_summary_html:
        raise Http404("인사이트 요약이 없습니다.")
    return HttpResponse(stock.insight_summary_html, content_type='text/html; charset=utf-8')


@xframe_options_sameorigin
def stock_insight_report_html(request, code):
    """인사이트 리포트 HTML 페이지"""
    from django.http import HttpResponse, Http404
    stock = get_object_or_404(Info, code=code)
    if not stock.insight_report_html:
        raise Http404("인사이트 리포트가 없습니다.")
    return HttpResponse(stock.insight_report_html, content_type='text/html; charset=utf-8')


def signal_chart_data(request, code):
    """신호 차트 데이터 API (최근 6개월 일봉)"""
    stock = get_object_or_404(Info, code=code)

    # 최근 120일 (약 6개월) 일봉 데이터
    daily_charts = DailyChart.objects.filter(stock=stock).order_by('-date')[:120]

    candle_data = []
    volume_data = []
    for d in reversed(daily_charts):
        time_str = d.date.strftime('%Y-%m-%d')
        candle_data.append({
            'time': time_str,
            'open': d.opening_price,
            'high': d.high_price,
            'low': d.low_price,
            'close': d.closing_price,
        })
        # 거래량 색상: 상승(빨강), 하락(파랑)
        volume_color = '#ef535080' if d.closing_price >= d.opening_price else '#2196f380'
        volume_data.append({
            'time': time_str,
            'value': d.trading_volume,
            'color': volume_color,
        })

    return JsonResponse({
        'success': True,
        'stock_name': stock.name,
        'current_price': stock.current_price,
        'candle_data': candle_data,
        'volume_data': volume_data,
    })


def etf_signal_chart_data(request, code):
    """ETF 신호 차트 데이터 API (최근 6개월 일봉)"""
    from .models import InfoETF, DailyChartETF

    etf = get_object_or_404(InfoETF, code=code)

    # 최근 120일 (약 6개월) 일봉 데이터
    daily_charts = DailyChartETF.objects.filter(etf=etf).order_by('-date')[:120]

    candle_data = []
    volume_data = []
    for d in reversed(daily_charts):
        time_str = d.date.strftime('%Y-%m-%d')
        candle_data.append({
            'time': time_str,
            'open': d.opening_price,
            'high': d.high_price,
            'low': d.low_price,
            'close': d.closing_price,
        })
        # 거래량 색상: 상승(빨강), 하락(파랑)
        volume_color = '#ef535080' if d.closing_price >= d.opening_price else '#2196f380'
        volume_data.append({
            'time': time_str,
            'value': d.trading_volume,
            'color': volume_color,
        })

    return JsonResponse({
        'success': True,
        'etf_name': etf.name,
        'current_price': etf.current_price,
        'candle_data': candle_data,
        'volume_data': volume_data,
    })


# 텔레그램 채널 목록 (채널ID: 표시명)
TELEGRAM_CHANNELS = {
    '@sunstudy1004': '선진짱',
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
    '@stock_ai_agent': '프리즘인사이트',
    '@sejongdata2013': '세종기업데이터',
    '@tazastock': '타자',
    3796408122: 'IB투자파트너스',
}


@require_GET
def search_telegram(request):
    """텔레그램 채널 검색 API"""
    keyword = request.GET.get('keyword', '')
    limit = int(request.GET.get('limit', 30))
    days = int(request.GET.get('days', 120))  # 기본 120일

    if not keyword:
        return JsonResponse({'error': '검색어가 필요합니다.'}, status=400)

    api_id = config('TELEGRAM_API_ID')
    api_hash = config('TELEGRAM_API_HASH')

    async def search():
        async with TelegramClient('telegram_session', api_id, api_hash) as client:
            # 지정된 기간 전 날짜
            date_limit = datetime.now(timezone.utc) - timedelta(days=days)

            # 채널별 결과
            by_channel = {}

            for channel in TELEGRAM_CHANNELS.keys():
                channel_key = str(channel)
                try:
                    entity = await client.get_entity(channel)
                    msgs = await client.get_messages(entity, search=keyword, limit=limit)

                    channel_msgs = [m for m in msgs if m.text]

                    # 기간 이내 메시지만 필터링
                    recent_msgs = [m for m in channel_msgs if m.date >= date_limit]

                    # 날짜별 그룹핑
                    by_date = defaultdict(list)
                    for msg in recent_msgs:
                        date_str = msg.date.strftime('%Y-%m-%d')
                        by_date[date_str].append({
                            'time': msg.date.strftime('%H:%M'),
                            'text': msg.text
                        })

                    by_channel[channel_key] = dict(by_date)
                except Exception:
                    by_channel[channel_key] = {}  # 채널 접근 실패

            return by_channel

    try:
        results = asyncio.run(search())
        return JsonResponse({
            'success': True,
            'keyword': keyword,
            'channel_names': {str(k): v for k, v in TELEGRAM_CHANNELS.items()},
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


def _annotate_holdings(holdings):
    """템플릿에서 쓸 원금(평가금액 - 평가손익) 추가"""
    for h in holdings:
        if h.eval_amount is not None and h.eval_profit is not None:
            h.principal = h.eval_amount - h.eval_profit
        else:
            h.principal = None
    return holdings


def market(request):
    """시황 페이지"""
    from django.db.models import Max, Min
    from .models import SystemSetting, CustomSector, DailyAccountSnapshot, Holding

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
        kospi_prev_close = float(kospi_charts[-2].closing_price)
    else:
        kospi_change = 0
        kospi_change_rate = 0
        kospi_prev_close = 0

    if len(kosdaq_charts) >= 2:
        kosdaq_change = float(kosdaq_charts[-1].closing_price - kosdaq_charts[-2].closing_price)
        kosdaq_change_rate = round(kosdaq_change / float(kosdaq_charts[-2].closing_price) * 100, 2)
        kosdaq_prev_close = float(kosdaq_charts[-2].closing_price)
    else:
        kosdaq_change = 0
        kosdaq_change_rate = 0
        kosdaq_prev_close = 0

    # 52주 고가/저가
    if kospi_latest:
        fifty_two_weeks_ago = kospi_latest.date - timedelta(weeks=52)
        kospi_52w = IndexChart.objects.filter(
            code='KOSPI', date__gte=fifty_two_weeks_ago
        ).aggregate(high=Max('high_price'), low=Min('low_price'))
        kospi_52w_high = float(kospi_52w['high']) if kospi_52w['high'] else 0
        kospi_52w_low = float(kospi_52w['low']) if kospi_52w['low'] else 0
    else:
        kospi_52w_high = 0
        kospi_52w_low = 0

    if kosdaq_latest:
        fifty_two_weeks_ago = kosdaq_latest.date - timedelta(weeks=52)
        kosdaq_52w = IndexChart.objects.filter(
            code='KOSDAQ', date__gte=fifty_two_weeks_ago
        ).aggregate(high=Max('high_price'), low=Min('low_price'))
        kosdaq_52w_high = float(kosdaq_52w['high']) if kosdaq_52w['high'] else 0
        kosdaq_52w_low = float(kosdaq_52w['low']) if kosdaq_52w['low'] else 0
    else:
        kosdaq_52w_high = 0
        kosdaq_52w_low = 0

    # MarketTrend data (top 20 per market)
    kospi_trends = MarketTrend.objects.filter(market='KOSPI').order_by('-date')[:20]
    kosdaq_trends = MarketTrend.objects.filter(market='KOSDAQ').order_by('-date')[:20]
    futures_trends = MarketTrend.objects.filter(market='FUTURES').order_by('-date')[:20]

    # Trend summary JSON (for JS tab switching)
    def trends_to_json(trends):
        return [
            {
                'individual': t.individual,
                'foreign': t.foreign,
                'institution': t.institution,
            }
            for t in trends
        ]

    # Raw trend data (120 days, for JS cumulative calculation)
    def get_raw_trend_data(market):
        trends = list(MarketTrend.objects.filter(market=market).order_by('-date')[:120])
        trends.reverse()  # oldest first
        return [
            {
                'date': t.date.strftime('%Y-%m-%d'),
                'individual': t.individual,
                'foreign': t.foreign,
                'institution': t.institution,
            }
            for t in trends
        ]

    kospi_raw_trends = get_raw_trend_data('KOSPI')
    kosdaq_raw_trends = get_raw_trend_data('KOSDAQ')
    futures_raw_trends = get_raw_trend_data('FUTURES')

    # 자산 스냅샷 (최근 60일치, 차트는 오름차순)
    asset_snapshots = list(DailyAccountSnapshot.objects.order_by('-date')[:60])
    asset_snapshots.reverse()

    asset_chart_data = [
        {
            'time': s.date.strftime('%Y-%m-%d'),
            'total_eval_amount': s.total_eval_amount or 0,
            'profit_rate': float(s.profit_rate) if s.profit_rate is not None else 0,
            'total_eval_profit': s.total_eval_profit,
            'deposit_balance': s.deposit_balance,
            'cash_weight': float(s.cash_weight) if s.cash_weight is not None else None,
        }
        for s in asset_snapshots
    ]

    asset_latest = asset_snapshots[-1] if asset_snapshots else None
    asset_prev = asset_snapshots[-2] if len(asset_snapshots) >= 2 else None

    def _delta(curr, prev):
        if curr is None or prev is None:
            return None
        diff = float(curr) - float(prev)
        pct = (diff / float(prev) * 100) if float(prev) != 0 else None
        return {
            'diff': diff,
            'pct': round(pct, 2) if pct is not None else None,
        }

    asset_changes = {}
    if asset_latest and asset_prev:
        asset_changes = {
            'estimated_asset': _delta(asset_latest.estimated_asset, asset_prev.estimated_asset),
            'total_eval_amount': _delta(asset_latest.total_eval_amount, asset_prev.total_eval_amount),
            'total_eval_profit': _delta(asset_latest.total_eval_profit, asset_prev.total_eval_profit),
            'profit_rate': _delta(asset_latest.profit_rate, asset_prev.profit_rate),
            'total_buy_amount': _delta(asset_latest.total_buy_amount, asset_prev.total_buy_amount),
            'deposit_balance': _delta(asset_latest.deposit_balance, asset_prev.deposit_balance),
            'cash_weight': _delta(asset_latest.cash_weight, asset_prev.cash_weight),
        }

    context = {
        'kospi_candle_data': json.dumps(kospi_candle_data),
        'kospi_volume_data': json.dumps(kospi_volume_data),
        'kosdaq_candle_data': json.dumps(kosdaq_candle_data),
        'kosdaq_volume_data': json.dumps(kosdaq_volume_data),
        'kospi_latest': kospi_latest,
        'kosdaq_latest': kosdaq_latest,
        'kospi_change': kospi_change,
        'kospi_change_rate': kospi_change_rate,
        'kospi_prev_close': kospi_prev_close,
        'kosdaq_change': kosdaq_change,
        'kosdaq_change_rate': kosdaq_change_rate,
        'kosdaq_prev_close': kosdaq_prev_close,
        'kospi_52w_high': kospi_52w_high,
        'kospi_52w_low': kospi_52w_low,
        'kosdaq_52w_high': kosdaq_52w_high,
        'kosdaq_52w_low': kosdaq_52w_low,
        'kospi_trends': kospi_trends,
        'kosdaq_trends': kosdaq_trends,
        'futures_trends': futures_trends,
        'kospi_trends_json': json.dumps(trends_to_json(kospi_trends)),
        'kosdaq_trends_json': json.dumps(trends_to_json(kosdaq_trends)),
        'futures_trends_json': json.dumps(trends_to_json(futures_trends)),
        'kospi_raw_trends': json.dumps(kospi_raw_trends),
        'kosdaq_raw_trends': json.dumps(kosdaq_raw_trends),
        'futures_raw_trends': json.dumps(futures_raw_trends),
        'saved_prompts': {s.key: s.value for s in SystemSetting.objects.filter(key__startswith='prompt_')},
        'interest_stocks_json': json.dumps([
            {'code': s.code, 'name': s.name, 'level': s.interest_level}
            for s in Info.objects.filter(interest_level__in=['super', 'normal', 'waiting']).order_by('-interest_level', 'name')
        ]),
        'custom_sectors_json': json.dumps([
            {'id': s.id, 'name': s.name}
            for s in CustomSector.objects.all().order_by('name')
        ]),
        'asset_chart_data': json.dumps(asset_chart_data),
        'asset_latest': asset_latest,
        'asset_changes': asset_changes,
        'holdings': _annotate_holdings(list(Holding.objects.select_related('info', 'info_etf').all())),
    }
    return render(request, 'stocks/market.html', context)


@require_GET
def fetch_morning_market(request):
    """모닝시황 API - 텔레그램 AIMarketDeepDive 채널에서 오늘 '모닝 시황' 검색"""
    api_id = config('TELEGRAM_API_ID', default='')
    api_hash = config('TELEGRAM_API_HASH', default='')

    if not api_id or not api_hash:
        return JsonResponse({'error': '텔레그램 API 설정이 없습니다.'}, status=500)

    async def search():
        from datetime import timezone, timedelta
        kst = timezone(timedelta(hours=9))

        async with TelegramClient('telegram_session', api_id, api_hash) as client:
            entity = await client.get_entity('@AIMarketDeepDive')
            msgs = await client.get_messages(entity, search='모닝 시황', limit=5)

            results = []
            latest_date = None
            for msg in msgs:
                if not msg.text:
                    continue
                msg_kst = msg.date.astimezone(kst)
                msg_date = msg_kst.strftime('%Y-%m-%d')
                if latest_date is None:
                    latest_date = msg_date
                if msg_date == latest_date:
                    results.append({
                        'date': msg_date,
                        'time': msg_kst.strftime('%H:%M'),
                        'text': msg.text,
                    })
            return results

    try:
        results = asyncio.run(search())
        return JsonResponse({'success': True, 'results': results})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_GET
def fetch_habono(request):
    """하보노 카테고리별 최신 5개 가져오기"""
    import requests as http_requests
    from bs4 import BeautifulSoup

    category = request.GET.get('category', '18f2bc7d3da000aui')
    limit = int(request.GET.get('limit', 5))
    url = f'https://contents.premium.naver.com/habono/habono2/contents?categoryId={category}'
    try:
        resp = http_requests.get(url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        results = []
        items = soup.select('li.content_item')[:limit]
        for item in items:
            link_el = item.select_one('a.content_text_link')
            title_el = item.select_one('strong.content_title')
            date_el = item.select('span.content_info_text')

            if not link_el or not title_el:
                continue

            href = link_el.get('href', '')
            if href and not href.startswith('http'):
                href = 'https://contents.premium.naver.com' + href

            date_text = ''
            for span in date_el:
                text = span.get_text(strip=True)
                if '.' in text and any(c.isdigit() for c in text):
                    date_text = text
                    break

            results.append({
                'title': title_el.get_text(strip=True),
                'url': href,
                'date': date_text,
            })

        return JsonResponse({'success': True, 'results': results})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_GET
def diary_list(request):
    """투자일기 목록 API (페이지네이션)"""
    limit = int(request.GET.get('limit', 20))
    offset = int(request.GET.get('offset', 0))
    total = MarketDiary.objects.count()
    entries = MarketDiary.objects.all()[offset:offset + limit]

    # 코스피 종가 + 등락률 계산을 위해 날짜 목록 수집
    dates = [e.date for e in entries]
    if dates:
        # 이전 날짜 등락률 계산을 위해 추가 날짜도 가져옴
        kospi_data = {
            ic.date: float(ic.closing_price)
            for ic in IndexChart.objects.filter(code='KOSPI').order_by('-date')[:300]
        }
    else:
        kospi_data = {}

    # 날짜순 정렬된 코스피 날짜 목록
    sorted_kospi_dates = sorted(kospi_data.keys())

    results = []
    for entry in entries:
        kospi_price = kospi_data.get(entry.date)
        kospi_change = None

        if kospi_price and sorted_kospi_dates:
            # 해당 날짜 또는 이전 가장 가까운 거래일 찾기
            idx = None
            for i, d in enumerate(sorted_kospi_dates):
                if d <= entry.date:
                    idx = i
            if idx is not None:
                kospi_price = kospi_data[sorted_kospi_dates[idx]]
                if idx > 0:
                    prev_price = kospi_data[sorted_kospi_dates[idx - 1]]
                    kospi_change = round((kospi_price - prev_price) / prev_price * 100, 2)

        results.append({
            'id': entry.id,
            'date': entry.date.strftime('%Y-%m-%d'),
            'content': entry.content,
            'kospi_price': kospi_price,
            'kospi_change': kospi_change,
            'updated_at': entry.updated_at.strftime('%Y-%m-%d %H:%M'),
        })

    return JsonResponse({
        'success': True,
        'results': results,
        'total': total,
        'has_more': offset + limit < total,
    })


@require_POST
def diary_save(request):
    """투자일기 저장 API"""
    date_str = request.POST.get('date', '').strip()
    content = request.POST.get('content', '').strip()

    if not date_str or not content:
        return JsonResponse({'error': '날짜와 내용을 입력하세요.'}, status=400)

    try:
        date_val = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': '올바른 날짜 형식이 아닙니다.'}, status=400)

    if MarketDiary.objects.filter(date=date_val).exists():
        return JsonResponse({'error': '해당 날짜에 이미 일기가 있습니다.'}, status=400)

    entry = MarketDiary.objects.create(date=date_val, content=content)
    return JsonResponse({'success': True, 'id': entry.id})


@require_POST
def diary_update(request, diary_id):
    """투자일기 수정 API"""
    entry = get_object_or_404(MarketDiary, id=diary_id)
    content = request.POST.get('content', '').strip()
    date_str = request.POST.get('date', '').strip()

    if not content:
        return JsonResponse({'error': '내용을 입력하세요.'}, status=400)

    if date_str:
        try:
            new_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            if new_date != entry.date and MarketDiary.objects.filter(date=new_date).exists():
                return JsonResponse({'error': '해당 날짜에 이미 일기가 있습니다.'}, status=400)
            entry.date = new_date
        except ValueError:
            pass

    entry.content = content
    entry.save()
    return JsonResponse({'success': True})


@require_POST
def diary_delete(request, diary_id):
    """투자일기 삭제 API"""
    entry = get_object_or_404(MarketDiary, id=diary_id)
    entry.delete()
    return JsonResponse({'success': True})


@require_GET
def stock_diary_list(request, code):
    """종목별 투자일지 목록 API"""
    limit = int(request.GET.get('limit', 20))
    offset = int(request.GET.get('offset', 0))
    total = StockDiary.objects.filter(stock_id=code).count()
    entries = StockDiary.objects.filter(stock_id=code)[offset:offset + limit]

    results = []
    for entry in entries:
        results.append({
            'id': entry.id,
            'date': entry.date.strftime('%Y-%m-%d'),
            'content': entry.content,
            'is_buy': entry.is_buy,
            'is_sell': entry.is_sell,
            'updated_at': entry.updated_at.strftime('%Y-%m-%d %H:%M'),
        })

    return JsonResponse({
        'success': True,
        'results': results,
        'total': total,
        'has_more': offset + limit < total,
    })


def _parse_bool(val):
    return str(val).lower() in ('1', 'true', 'on', 'yes')


@require_POST
def stock_diary_save(request, code):
    """종목별 투자일지 저장 API"""
    date_str = request.POST.get('date', '').strip()
    content = request.POST.get('content', '').strip()
    is_buy = _parse_bool(request.POST.get('is_buy', ''))
    is_sell = _parse_bool(request.POST.get('is_sell', ''))

    if not date_str or not content:
        return JsonResponse({'error': '날짜와 내용을 입력하세요.'}, status=400)

    try:
        date_val = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': '올바른 날짜 형식이 아닙니다.'}, status=400)

    stock = get_object_or_404(Info, code=code)

    if StockDiary.objects.filter(stock=stock, date=date_val).exists():
        return JsonResponse({'error': '해당 날짜에 이미 일지가 있습니다.'}, status=400)

    entry = StockDiary.objects.create(
        stock=stock, date=date_val, content=content,
        is_buy=is_buy, is_sell=is_sell,
    )
    if is_buy and not stock.is_holding:
        stock.is_holding = True
        stock.save(update_fields=['is_holding'])
    return JsonResponse({'success': True, 'id': entry.id})


@require_POST
def stock_diary_update(request, code, diary_id):
    """종목별 투자일지 수정 API"""
    entry = get_object_or_404(StockDiary, id=diary_id, stock_id=code)
    content = request.POST.get('content', '').strip()
    date_str = request.POST.get('date', '').strip()

    if not content:
        return JsonResponse({'error': '내용을 입력하세요.'}, status=400)

    if date_str:
        try:
            new_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            if new_date != entry.date and StockDiary.objects.filter(stock_id=code, date=new_date).exists():
                return JsonResponse({'error': '해당 날짜에 이미 일지가 있습니다.'}, status=400)
            entry.date = new_date
        except ValueError:
            pass

    if 'is_buy' in request.POST:
        entry.is_buy = _parse_bool(request.POST.get('is_buy'))
    if 'is_sell' in request.POST:
        entry.is_sell = _parse_bool(request.POST.get('is_sell'))

    entry.content = content
    entry.save()

    if entry.is_buy and not entry.stock.is_holding:
        entry.stock.is_holding = True
        entry.stock.save(update_fields=['is_holding'])

    return JsonResponse({'success': True})


@require_POST
def stock_diary_delete(request, code, diary_id):
    """종목별 투자일지 삭제 API"""
    entry = get_object_or_404(StockDiary, id=diary_id, stock_id=code)
    entry.delete()
    return JsonResponse({'success': True})


# ===== 종목별 이벤트 =====

@require_GET
def stock_event_list(request, code):
    """종목별 이벤트 목록 API"""
    from .models import StockEvent
    events = StockEvent.objects.filter(stock_id=code)
    results = []
    from datetime import date
    today = date.today()
    for ev in events:
        d_day = None
        if ev.date:
            delta = (ev.date - today).days
            d_day = delta
        results.append({
            'id': ev.id,
            'date': ev.date.strftime('%Y-%m-%d') if ev.date else None,
            'date_text': ev.date_text,
            'title': ev.title,
            'content': ev.content,
            'd_day': d_day,
        })
    return JsonResponse({'success': True, 'results': results})


@require_POST
def stock_event_save(request, code):
    """종목별 이벤트 저장 API"""
    from .models import StockEvent
    date_str = request.POST.get('date', '').strip()
    date_text = request.POST.get('date_text', '').strip()
    title = request.POST.get('title', '').strip()
    content = request.POST.get('content', '').strip()

    if not title:
        return JsonResponse({'error': '제목을 입력하세요.'}, status=400)
    if not date_text:
        return JsonResponse({'error': '날짜를 입력하세요.'}, status=400)

    date_val = None
    if date_str:
        try:
            date_val = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    stock = get_object_or_404(Info, code=code)
    max_order = StockEvent.objects.filter(stock=stock).order_by('-order').values_list('order', flat=True).first()
    next_order = (max_order or 0) + 1
    ev = StockEvent.objects.create(
        stock=stock, date=date_val, date_text=date_text,
        title=title, content=content, order=next_order
    )
    return JsonResponse({'success': True, 'id': ev.id})


@require_POST
def stock_event_update(request, code, event_id):
    """종목별 이벤트 수정 API"""
    from .models import StockEvent
    ev = get_object_or_404(StockEvent, id=event_id, stock_id=code)
    date_str = request.POST.get('date', '').strip()
    date_text = request.POST.get('date_text', '').strip()
    title = request.POST.get('title', '').strip()
    content = request.POST.get('content', '').strip()

    if not title:
        return JsonResponse({'error': '제목을 입력하세요.'}, status=400)
    if not date_text:
        return JsonResponse({'error': '날짜를 입력하세요.'}, status=400)

    ev.date = None
    if date_str:
        try:
            ev.date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    ev.date_text = date_text
    ev.title = title
    ev.content = content
    ev.save()
    return JsonResponse({'success': True})


@require_POST
def stock_event_delete(request, code, event_id):
    """종목별 이벤트 삭제 API"""
    from .models import StockEvent
    ev = get_object_or_404(StockEvent, id=event_id, stock_id=code)
    ev.delete()
    return JsonResponse({'success': True})


@require_POST
def stock_event_move(request, code, event_id):
    """종목별 이벤트 순서 이동 API"""
    from .models import StockEvent
    direction = request.POST.get('direction', '')
    events = list(StockEvent.objects.filter(stock_id=code))
    idx = next((i for i, e in enumerate(events) if e.id == event_id), None)
    if idx is None:
        return JsonResponse({'error': '이벤트를 찾을 수 없습니다.'}, status=404)
    if direction == 'up' and idx > 0:
        events[idx], events[idx - 1] = events[idx - 1], events[idx]
    elif direction == 'down' and idx < len(events) - 1:
        events[idx], events[idx + 1] = events[idx + 1], events[idx]
    for i, ev in enumerate(events):
        if ev.order != i:
            StockEvent.objects.filter(id=ev.id).update(order=i)
    return JsonResponse({'success': True})


@require_GET
def fetch_youtube_channel(request):
    """유튜브 채널 최신 영상 가져오기"""
    import requests as http_requests
    import re

    channel = request.GET.get('channel', '@3protv')
    limit = int(request.GET.get('limit', 15))

    url = f'https://www.youtube.com/{channel}/videos'
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        resp = http_requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()

        match = re.search(r'var ytInitialData = ({.*?});', resp.text)
        if not match:
            return JsonResponse({'error': '유튜브 데이터를 파싱할 수 없습니다.'}, status=500)

        data = json.loads(match.group(1))
        tabs = data['contents']['twoColumnBrowseResultsRenderer']['tabs']

        results = []
        for tab in tabs:
            if 'tabRenderer' in tab and tab['tabRenderer'].get('selected'):
                items = tab['tabRenderer']['content']['richGridRenderer']['contents']
                for item in items:
                    if 'richItemRenderer' not in item:
                        continue
                    vid = item['richItemRenderer']['content']['videoRenderer']
                    vid_id = vid['videoId']
                    title = vid['title']['runs'][0]['text']
                    published = ''
                    if 'publishedTimeText' in vid:
                        published = vid['publishedTimeText'].get('simpleText', '')

                    results.append({
                        'video_id': vid_id,
                        'title': title,
                        'thumbnail': f'https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg',
                        'url': f'https://www.youtube.com/watch?v={vid_id}',
                        'published': published,
                    })
                    if len(results) >= limit:
                        break
                break

        return JsonResponse({'success': True, 'results': results})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


_PUBLISHED_UNITS = {
    '분': 1,
    '시간': 60,
    '일': 60 * 24,
    '주': 60 * 24 * 7,
    '개월': 60 * 24 * 30,
    '달': 60 * 24 * 30,
    '년': 60 * 24 * 365,
}


def _parse_published_minutes(text):
    """'1일 전', '37분 전', '스트리밍 시간: 2시간 전' 등을 분 단위 정수로 변환. 실패 시 매우 큰 값."""
    import re
    if not text:
        return 10 ** 9
    if '방금' in text:
        return 0
    m = re.search(r'(\d+)\s*(분|시간|일|주|개월|달|년)', text)
    if not m:
        return 10 ** 9
    n = int(m.group(1))
    unit = m.group(2)
    return n * _PUBLISHED_UNITS.get(unit, 10 ** 6)


def fetch_youtube_search(request):
    """유튜브 키워드 검색 결과를 업로드 시점 기준 최신순으로 반환"""
    import requests as http_requests
    import re
    from urllib.parse import quote

    query = request.GET.get('q', '').strip()
    limit = int(request.GET.get('limit', 15))
    if not query:
        return JsonResponse({'error': '검색어가 없습니다.'}, status=400)

    # sp=CAISAhAB : 업로드 날짜 정렬 + 동영상 타입 필터
    url = f'https://www.youtube.com/results?search_query={quote(query)}&sp=CAISAhAB'
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        resp = http_requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()

        match = re.search(r'var ytInitialData = ({.*?});</script>', resp.text)
        if not match:
            return JsonResponse({'error': '유튜브 데이터를 파싱할 수 없습니다.'}, status=500)

        data = json.loads(match.group(1))
        sections = data['contents']['twoColumnSearchResultsRenderer']['primaryContents']['sectionListRenderer']['contents']

        candidates = []
        for section in sections:
            for item in section.get('itemSectionRenderer', {}).get('contents', []):
                vid = item.get('videoRenderer')
                if not vid:
                    continue
                vid_id = vid.get('videoId')
                if not vid_id:
                    continue
                title_runs = vid.get('title', {}).get('runs', [])
                title = title_runs[0]['text'] if title_runs else ''
                published = vid.get('publishedTimeText', {}).get('simpleText', '')
                channel = ''
                owner_runs = vid.get('ownerText', {}).get('runs', [])
                if owner_runs:
                    channel = owner_runs[0].get('text', '')

                candidates.append({
                    'video_id': vid_id,
                    'title': title,
                    'thumbnail': f'https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg',
                    'url': f'https://www.youtube.com/watch?v={vid_id}',
                    'published': published,
                    'channel': channel,
                    '_age': _parse_published_minutes(published),
                })

        candidates.sort(key=lambda r: r['_age'])
        results = [{k: v for k, v in r.items() if k != '_age'} for r in candidates[:limit]]
        return JsonResponse({'success': True, 'results': results})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_GET
def market_youtube_list(request):
    """시황 유튜브 목록 API (페이지네이션)"""
    from .models import MarketYoutubeVideo
    limit = int(request.GET.get('limit', 30))
    offset = int(request.GET.get('offset', 0))
    total = MarketYoutubeVideo.objects.count()
    videos = MarketYoutubeVideo.objects.all()[offset:offset + limit]
    results = []
    for v in videos:
        results.append({
            'id': v.id,
            'video_id': v.video_id,
            'title': v.title,
            'channel': v.channel,
            'note': v.my_opinion,
            'summary': v.summary,
            'url': v.url,
            'date': v.published_date.strftime('%Y-%m-%d') if v.published_date else v.created_at.strftime('%Y-%m-%d'),
        })
    return JsonResponse({'success': True, 'results': results, 'total': total, 'has_more': offset + limit < total})


@require_POST
def market_youtube_save(request):
    """시황 유튜브 저장 API - 링크로 저장 후 요약 입력"""
    import requests as http_requests
    import re
    from .models import MarketYoutubeVideo

    link = request.POST.get('link', '').strip()
    note = request.POST.get('note', '').strip()
    summary = request.POST.get('summary', '').strip()
    date_input = request.POST.get('date', '').strip()

    if not link:
        return JsonResponse({'error': '유튜브 링크를 입력하세요.'}, status=400)

    # video_id 추출
    video_id = None
    match = re.search(r'[?&]v=([^&]+)', link)
    if match:
        video_id = match.group(1)
    else:
        match = re.search(r'youtu\.be/([^?&]+)', link)
        if match:
            video_id = match.group(1)
        else:
            match = re.search(r'shorts/([^?&]+)', link)
            if match:
                video_id = match.group(1)

    if not video_id:
        return JsonResponse({'error': '올바른 유튜브 링크가 아닙니다.'}, status=400)

    if MarketYoutubeVideo.objects.filter(video_id=video_id).exists():
        return JsonResponse({'error': '이미 저장된 영상입니다.'}, status=400)

    # 유튜브 페이지에서 제목, 채널명, 게시일 가져오기
    title = ''
    channel = ''
    published_date = None
    try:
        url = f'https://www.youtube.com/watch?v={video_id}'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'ko-KR,ko;q=0.9',
        }
        resp = http_requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()

        def decode_unicode(s):
            try:
                return json.loads(f'"{s}"')
            except:
                return s

        title_match = re.search(r'"title":"([^"]+)"', resp.text)
        if title_match:
            title = decode_unicode(title_match.group(1))
        channel_match = re.search(r'"ownerChannelName":"([^"]+)"', resp.text)
        if channel_match:
            channel = decode_unicode(channel_match.group(1))

        # 게시일 추출 (여러 패턴 시도)
        date_patterns = [
            r'"publishDate"\s*:\s*"(\d{4}-\d{2}-\d{2})',
            r'"uploadDate"\s*:\s*"(\d{4}-\d{2}-\d{2})',
            r'"dateText"\s*:\s*\{\s*"simpleText"\s*:\s*"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})',
        ]
        for pattern in date_patterns:
            date_match = re.search(pattern, resp.text)
            if date_match:
                groups = date_match.groups()
                if len(groups) == 1:
                    published_date = datetime.strptime(groups[0], '%Y-%m-%d').date()
                else:
                    published_date = datetime(int(groups[0]), int(groups[1]), int(groups[2])).date()
                break
    except:
        pass

    if not title:
        title = f'영상 {video_id}'

    video = MarketYoutubeVideo.objects.create(
        video_id=video_id,
        title=title,
        channel=channel,
        note=note,
        summary=summary,
        published_date=datetime.strptime(date_input, '%Y-%m-%d').date() if date_input else (published_date or datetime.now().date()),
    )

    return JsonResponse({
        'success': True,
        'id': video.id,
        'video_id': video.video_id,
        'title': video.title,
        'channel': video.channel,
        'summary': video.summary,
        'url': video.url,
        'date': video.published_date.strftime('%Y-%m-%d') if video.published_date else video.created_at.strftime('%Y-%m-%d'),
    })


@require_POST
def market_youtube_update(request, video_id):
    """시황 유튜브 수정 API"""
    from .models import MarketYoutubeVideo
    video = get_object_or_404(MarketYoutubeVideo, id=video_id)
    note = request.POST.get('note')
    if note is not None:
        video.note = note.strip()
    summary = request.POST.get('summary')
    if summary is not None:
        video.summary = summary.strip()
    date_input = request.POST.get('date', '').strip()
    if date_input:
        video.published_date = datetime.strptime(date_input, '%Y-%m-%d').date()
    video.save()
    return JsonResponse({'success': True})


@require_POST
def market_youtube_delete(request, video_id):
    """시황 유튜브 삭제 API"""
    from .models import MarketYoutubeVideo
    video = get_object_or_404(MarketYoutubeVideo, id=video_id)
    video.delete()
    return JsonResponse({'success': True})


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
        import re
        summary = request.POST.get('summary', '')
        summary = re.sub(r'\[cite_start\]', '', summary)
        summary = re.sub(r'\[cite:\s*[\d,\s]+\]', '', summary)
        nodaji.summary = summary
        nodaji.my_opinion = request.POST.get('my_opinion', '')
        nodaji.save()

        # AJAX 요청이면 JSON 응답
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True})

        return redirect('stocks:nodaji_summary', nodaji_id=nodaji_id)

    from .models import SystemSetting
    nodaji_prompt = SystemSetting.objects.filter(key='prompt_nodaji').values_list('value', flat=True).first() or ''
    prompt_summary = SystemSetting.objects.filter(key='prompt_summary').values_list('value', flat=True).first() or ''

    return render(request, 'stocks/nodaji_summary.html', {
        'nodaji': nodaji,
        'nodaji_prompt': nodaji_prompt,
        'prompt_summary': prompt_summary,
    })


def report_summary(request, report_id):
    """리포트 요약 저장 API"""
    report = get_object_or_404(Report, id=report_id)

    if request.method == 'POST':
        summary = request.POST.get('summary', '')
        report.summary = summary
        report.save()

        # AJAX 요청이면 JSON 응답
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/x-www-form-urlencoded':
            return JsonResponse({'success': True})

        messages.success(request, '요약이 저장되었습니다.')
        return redirect('stocks:stock_edit', code=report.stock.code)

    return JsonResponse({'error': 'POST 요청만 가능합니다.'}, status=405)


@require_GET
def fetch_more_reports(request, code):
    """리포트 더 가져오기 API"""
    stock = get_object_or_404(Info, code=code)
    offset = int(request.GET.get('offset', 20))
    limit = int(request.GET.get('limit', 20))

    reports = Report.objects.filter(stock=stock).order_by('-date')[offset:offset + limit]

    # 괴리율 계산을 위한 일봉 데이터
    report_dates = [r.date for r in reports]
    if report_dates:
        daily_prices = DailyChart.objects.filter(
            stock=stock,
            date__in=report_dates
        ).values('date', 'closing_price')
        price_by_date = {d['date']: d['closing_price'] for d in daily_prices}
    else:
        price_by_date = {}

    result = []
    for r in reports:
        gap_rate = None
        if r.target_price and r.date in price_by_date:
            closing = price_by_date[r.date]
            gap_rate = round((r.target_price / closing - 1) * 100, 1)

        result.append({
            'id': r.id,
            'date': r.date.strftime('%y/%m/%d'),
            'title': r.title,
            'author': r.author,
            'provider': r.provider,
            'target_price': r.target_price,
            'gap_rate': gap_rate,
            'summary': r.summary or '',
        })

    return JsonResponse({
        'success': True,
        'reports': result,
        'has_more': Report.objects.filter(stock=stock).count() > offset + limit
    })


@require_GET
def fetch_more_nodaji(request, code):
    """노다지 더 가져오기 API"""
    stock = get_object_or_404(Info, code=code)
    offset = int(request.GET.get('offset', 20))
    limit = int(request.GET.get('limit', 20))

    nodaji_list = Nodaji.objects.filter(
        stock=stock,
        title__contains=stock.name
    ).order_by('-date')[offset:offset + limit]

    result = []
    for n in nodaji_list:
        result.append({
            'id': n.id,
            'date': n.date.strftime('%y/%m/%d') if n.date else '-',
            'title': n.title,
            'link': n.link,
            'summary': n.summary or '',
        })

    total = Nodaji.objects.filter(stock=stock, title__contains=stock.name).count()

    return JsonResponse({
        'success': True,
        'nodaji': result,
        'has_more': total > offset + limit
    })


@require_GET
def search_stock(request):
    """종목/ETF 검색 API"""
    from django.db.models import Q
    from .models import InfoETF

    query = request.GET.get('q', request.GET.get('keyword', '')).strip()
    if not query:
        return JsonResponse({'success': False, 'error': '검색어를 입력하세요.'})

    stocks = Info.objects.filter(
        Q(name__icontains=query) | Q(code__icontains=query)
    )[:10]

    etfs = InfoETF.objects.filter(
        Q(name__icontains=query) | Q(code__icontains=query)
    )[:5]

    results = [{'code': s.code, 'name': s.name, 'type': 'stock'} for s in stocks]
    results += [{'code': e.code, 'name': e.name, 'type': 'etf'} for e in etfs]

    return JsonResponse({'success': True, 'stocks': results, 'results': results})


@require_GET
def fetch_stock_prompt_data(request, code):
    """종목 프롬프트 데이터 조회 API"""
    from .models import YoutubeVideo

    stock = get_object_or_404(Info, code=code)

    # 리포트 최근 5개 (같은 날짜면 1개만)
    all_reports = Report.objects.filter(stock=stock).order_by('-date')
    seen_dates = set()
    reports = []
    for r in all_reports:
        if r.date not in seen_dates:
            reports.append(r)
            seen_dates.add(r.date)
            if len(reports) >= 5:
                break

    # 유튜브 저장된 영상 (최근 5개)
    youtube_videos = YoutubeVideo.objects.filter(stock=stock).order_by('-id')[:5]

    # 노다지 (요약 있는 것만, 최근 3개)
    nodaji_list = Nodaji.objects.filter(
        stock=stock,
        title__contains=stock.name
    ).exclude(summary__isnull=True).exclude(summary='').order_by('-date')[:3]

    # 텍스트 형식으로 변환
    lines = []
    lines.append(f"=== {stock.name} ({stock.code}) 데이터 ===\n")

    # 리포트
    lines.append("## 리포트 (최근 5일)")
    if reports:
        for r in reports:
            date_str = r.date.strftime('%Y-%m-%d') if r.date else '-'
            lines.append(f"- [{date_str}] {r.title} / {r.author} / {r.provider}")
    else:
        lines.append("- 없음")
    lines.append("")

    # 유튜브
    lines.append("## 유튜브 (최근 5개)")
    if youtube_videos:
        for v in youtube_videos:
            lines.append(f"- {v.title}")
            lines.append(f"  링크: {v.link}")
            lines.append(f"  채널: {v.channel}, {v.published}")
    else:
        lines.append("- 없음")
    lines.append("")

    # 노다지
    lines.append("## 노다지 IR노트 (최근 3개)")
    if nodaji_list:
        import re
        from bs4 import BeautifulSoup
        for n in nodaji_list:
            date_str = n.date.strftime('%Y-%m-%d') if n.date else '-'
            lines.append(f"- [{date_str}] {n.title}")
            if n.summary:
                # HTML -> 텍스트 변환
                soup = BeautifulSoup(n.summary, 'html.parser')
                summary = soup.get_text(separator='\n')
                # 연속된 빈 줄/공백 정리
                summary = re.sub(r'\n\s*\n+', '\n', summary)
                # citation 제거 (모든 [cite...] 형식)
                summary = re.sub(r'\[cite_start\]', '', summary)
                summary = re.sub(r'\[cite_end\]', '', summary)
                summary = re.sub(r'\[cite:\s*\d+\]', '', summary)
                summary = re.sub(r'\[cite:\s*[\d,\s]+\]', '', summary)
                summary = re.sub(r'\[citexx\]', '', summary)
                summary = re.sub(r'\[/cite\]', '', summary)
                # 요약 내용 전체 (빈 줄 제외)
                for sl in summary.strip().split('\n'):
                    if sl.strip():  # 빈 줄 제외
                        lines.append(f"  {sl.strip()}")
            lines.append("")
    else:
        lines.append("- 없음")

    return JsonResponse({
        'success': True,
        'data': '\n'.join(lines)
    })


@require_GET
def fetch_stock_data_loader(request, code):
    """종목 데이터 불러오기 API (선택적 데이터 로드)"""
    import re
    from bs4 import BeautifulSoup
    from .models import YoutubeVideo, News, TelegramMessage, StockQuestionReport

    stock = get_object_or_404(Info, code=code)

    # 선택된 데이터 타입 (쉼표로 구분)
    types = request.GET.get('types', '').split(',')

    def html_to_text(html):
        """HTML을 텍스트로 변환"""
        if not html:
            return ''
        soup = BeautifulSoup(html, 'html.parser')
        text = soup.get_text(separator='\n')
        # 연속된 빈 줄 정리
        text = re.sub(r'\n\s*\n+', '\n\n', text)
        # citation 제거
        text = re.sub(r'\[cite_start\]', '', text)
        text = re.sub(r'\[cite_end\]', '', text)
        text = re.sub(r'\[cite:\s*[\d,\s]+\]', '', text)
        text = re.sub(r'\[/cite\]', '', text)
        return text.strip()

    lines = []
    lines.append(f"=== {stock.name} ({stock.code}) 데이터 ===\n")


    # 핵심 브리핑
    if 'key_briefing' in types:
        lines.append("## 핵심 브리핑")
        if stock.key_briefing:
            lines.append(stock.key_briefing)
        else:
            lines.append("- 저장된 데이터가 없습니다.")
        lines.append("")

    # 인사이트
    if 'insight' in types:
        lines.append("## 인사이트")
        if stock.insight_summary_html:
            lines.append(html_to_text(stock.insight_summary_html))
        elif stock.insight_report_html:
            lines.append(html_to_text(stock.insight_report_html))
        else:
            lines.append("- 저장된 데이터가 없습니다.")
        lines.append("")

    # 질문리포트 (최대 10개)
    if 'question_report' in types:
        lines.append("## 질문리포트 (최대 10개)")
        qr_list = StockQuestionReport.objects.filter(stock=stock).order_by('-id')[:10]
        if qr_list:
            for qr in qr_list:
                lines.append(f"\n### Q: {qr.question}")
                if qr.report:
                    # 마크다운은 그대로, HTML은 텍스트로 변환
                    if qr.report_type == 'markdown':
                        lines.append(qr.report)
                    else:
                        lines.append(html_to_text(qr.report))
        else:
            lines.append("- 저장된 데이터가 없습니다.")
        lines.append("")

    # 노다지 (요약 풀로 최대 5개)
    if 'nodaji' in types:
        lines.append("## 노다지 IR노트 (최대 5개)")
        nodaji_list = Nodaji.objects.filter(
            stock=stock,
            title__contains=stock.name
        ).exclude(summary__isnull=True).exclude(summary='').order_by('-date')[:5]
        if nodaji_list:
            for n in nodaji_list:
                date_str = n.date.strftime('%Y-%m-%d') if n.date else '-'
                lines.append(f"\n### [{date_str}] {n.title}")
                if n.summary:
                    summary = html_to_text(n.summary)
                    lines.append(summary)
        else:
            lines.append("- 저장된 데이터가 없습니다.")
        lines.append("")

    # 리포트 (최신 10개)
    if 'report' in types:
        lines.append("## 리포트 (최신 10개)")
        all_reports = Report.objects.filter(stock=stock).order_by('-date')
        seen_dates = set()
        reports = []
        for r in all_reports:
            if r.date not in seen_dates:
                reports.append(r)
                seen_dates.add(r.date)
                if len(reports) >= 10:
                    break
        if reports:
            for r in reports:
                date_str = r.date.strftime('%Y-%m-%d') if r.date else '-'
                lines.append(f"- [{date_str}] {r.title} / {r.author} / {r.provider}")
        else:
            lines.append("- 저장된 데이터가 없습니다.")
        lines.append("")

    # 유튜브 (저장된 링크, 제목 최대 10개)
    if 'youtube' in types:
        lines.append("## 유튜브 (최대 10개)")
        youtube_list = YoutubeVideo.objects.filter(stock=stock).order_by('-id')[:10]
        if youtube_list:
            for v in youtube_list:
                lines.append(f"- {v.title}")
                lines.append(f"  링크: {v.link}")
                if v.channel:
                    lines.append(f"  채널: {v.channel}")
        else:
            lines.append("- 저장된 데이터가 없습니다.")
        lines.append("")

    # 뉴스 (최대 10개)
    if 'news' in types:
        lines.append("## 뉴스 (최대 10개)")
        news_list = News.objects.filter(stock=stock).order_by('-id')[:10]
        if news_list:
            for n in news_list:
                lines.append(f"- {n.title}")
                lines.append(f"  링크: {n.link}")
        else:
            lines.append("- 저장된 데이터가 없습니다.")
        lines.append("")

    # 텔레그램
    if 'telegram' in types:
        lines.append("## 텔레그램")
        telegram_list = TelegramMessage.objects.filter(stock=stock).order_by('-id')[:10]
        if telegram_list:
            for t in telegram_list:
                channel_name = t.channel_name or t.channel
                lines.append(f"\n### {channel_name}")
                lines.append(t.text[:500] if t.text else '')
        else:
            lines.append("- 저장된 데이터가 없습니다.")
        lines.append("")

    # 메모
    if 'memo' in types:
        lines.append("## 메모")
        if stock.memo:
            lines.append(html_to_text(stock.memo))
        else:
            lines.append("- 저장된 데이터가 없습니다.")
        lines.append("")

    return JsonResponse({
        'success': True,
        'data': '\n'.join(lines)
    })


@require_GET
def fetch_stock_data_loader_with_summary(request, code):
    """종목 데이터 불러오기 API (설정된 데이터 타입 + 요약 포함)

    핵심브리핑 프롬프트 만들기용
    - 설정 페이지에서 선택한 데이터 타입만 불러오기
    - 데이터 먼저, 프롬프트 나중에
    """
    import re
    from bs4 import BeautifulSoup
    from .models import YoutubeVideo, News, TelegramMessage, StockQuestionReport, StockUploadedReport, SystemSetting

    stock = get_object_or_404(Info, code=code)

    # 저장된 데이터 타입 가져오기
    try:
        saved_types = SystemSetting.objects.get(key='briefing_data_types').value
        data_types = [t for t in saved_types.split(',') if t]  # 빈 문자열 제거
        if not data_types:
            data_types = ['analysis', 'key_briefing', 'nodaji', 'report', 'youtube', 'news', 'telegram', 'memo']
    except SystemSetting.DoesNotExist:
        data_types = ['analysis', 'key_briefing', 'nodaji', 'report', 'youtube', 'news', 'telegram', 'memo']

    def html_to_text(html):
        """HTML을 텍스트로 변환"""
        if not html:
            return ''
        soup = BeautifulSoup(html, 'html.parser')
        text = soup.get_text(separator='\n')
        text = re.sub(r'\n\s*\n+', '\n\n', text)
        text = re.sub(r'\[cite_start\]', '', text)
        text = re.sub(r'\[cite_end\]', '', text)
        text = re.sub(r'\[cite:\s*[\d,\s]+\]', '', text)
        text = re.sub(r'\[/cite\]', '', text)
        return text.strip()

    lines = []
    lines.append(f"=== {stock.name} ({stock.code}) 데이터 ===\n")

# 2. 핵심 브리핑
    if 'key_briefing' in data_types:
        lines.append("## 핵심 브리핑")
        if stock.key_briefing:
            lines.append(stock.key_briefing)
        else:
            lines.append("- 저장된 데이터가 없습니다.")
        lines.append("")


    # 3. 노다지 (요약 포함, 최대 5개)
    if 'nodaji' in data_types:
        lines.append("## 노다지 IR노트 (최대 5개)")
        nodaji_list = Nodaji.objects.filter(
            stock=stock,
            title__contains=stock.name
        ).exclude(summary__isnull=True).exclude(summary='').order_by('-date')[:5]
        if nodaji_list:
            for n in nodaji_list:
                date_str = n.date.strftime('%Y-%m-%d') if n.date else '-'
                lines.append(f"\n### [{date_str}] {n.title}")
                if n.summary:
                    summary = html_to_text(n.summary)
                    lines.append(f"요약:\n{summary}")
        else:
            lines.append("- 저장된 데이터가 없습니다.")
        lines.append("")

    # 4. 리포트 (요약 포함, 최신 10개)
    if 'report' in data_types:
        lines.append("## 애널리스트 리포트 (최신 10개)")
        all_reports = Report.objects.filter(stock=stock).order_by('-date')
        seen_dates = set()
        reports = []
        for r in all_reports:
            if r.date not in seen_dates:
                reports.append(r)
                seen_dates.add(r.date)
                if len(reports) >= 10:
                    break
        if reports:
            for r in reports:
                date_str = r.date.strftime('%Y-%m-%d') if r.date else '-'
                lines.append(f"\n### [{date_str}] {r.title}")
                lines.append(f"작성자: {r.author} / 증권사: {r.provider}")
                if r.summary:
                    summary_text = html_to_text(r.summary)
                    lines.append(f"요약:\n{summary_text}")
                else:
                    lines.append("요약: (요약 없음)")
        else:
            lines.append("- 저장된 데이터가 없습니다.")
        lines.append("")

    # 5. 유튜브 (요약 포함, 최대 10개)
    if 'youtube' in data_types:
        lines.append("## 유튜브 (최대 10개)")
        youtube_list = YoutubeVideo.objects.filter(stock=stock).order_by('-id')[:10]
        if youtube_list:
            for v in youtube_list:
                lines.append(f"\n### {v.title}")
                if v.channel:
                    lines.append(f"채널: {v.channel}")
                if v.summary:
                    summary_text = html_to_text(v.summary)
                    lines.append(f"요약:\n{summary_text}")
                else:
                    lines.append("요약: (요약 없음)")
        else:
            lines.append("- 저장된 데이터가 없습니다.")
        lines.append("")

    # 6. 뉴스 (요약 포함, 최대 10개)
    if 'news' in data_types:
        lines.append("## 뉴스 (최대 10개)")
        news_list = News.objects.filter(stock=stock).order_by('-id')[:10]
        if news_list:
            for n in news_list:
                lines.append(f"\n### {n.title}")
                if n.summary:
                    summary_text = html_to_text(n.summary)
                    lines.append(f"요약:\n{summary_text}")
                else:
                    lines.append("요약: (요약 없음)")
        else:
            lines.append("- 저장된 데이터가 없습니다.")
        lines.append("")

    # 7. 텔레그램 (요약 포함, 최대 10개)
    if 'telegram' in data_types:
        lines.append("## 텔레그램 (최대 10개)")
        telegram_list = TelegramMessage.objects.filter(stock=stock).order_by('-id')[:10]
        if telegram_list:
            for t in telegram_list:
                channel_name = t.channel_name or t.channel
                lines.append(f"\n### {channel_name}")
                lines.append(t.text[:500] if t.text else '')
                if t.summary:
                    summary_text = html_to_text(t.summary)
                    lines.append(f"요약:\n{summary_text}")
        else:
            lines.append("- 저장된 데이터가 없습니다.")
        lines.append("")

    # 8. 메모
    if 'memo' in data_types:
        lines.append("## 메모")
        if stock.memo:
            lines.append(html_to_text(stock.memo))
        else:
            lines.append("- 저장된 데이터가 없습니다.")
        lines.append("")

    # 9. 리서치 (질문리포트, 최대 10개)
    if 'research' in data_types:
        lines.append("## 리서치 (최대 10개)")
        qr_list = StockQuestionReport.objects.filter(stock=stock).order_by('-id')[:10]
        if qr_list:
            for qr in qr_list:
                lines.append(f"\n### Q: {qr.question}")
                if qr.report:
                    # 마크다운은 그대로, HTML은 텍스트로 변환
                    if qr.report_type == 'markdown':
                        lines.append(qr.report)
                    else:
                        lines.append(html_to_text(qr.report))
        else:
            lines.append("- 저장된 데이터가 없습니다.")
        lines.append("")

    # 프롬프트 추가 (데이터 뒤에)
    try:
        saved_prompt = SystemSetting.objects.get(key='prompt_briefing').value
        if saved_prompt:
            lines.append("\n---\n")
            lines.append(saved_prompt)
    except SystemSetting.DoesNotExist:
        pass

    return JsonResponse({
        'success': True,
        'data': '\n'.join(lines)
    })


def _fetch_stock_data_loader_with_summary_valuation_REMOVED():
    """종목 데이터 불러오기 API (가치평가용) - REMOVED

    가치평가 프롬프트 만들기용
    - 설정 페이지에서 선택한 데이터 타입만 불러오기
    - 데이터 먼저, 프롬프트 나중에
    """
    import re
    from bs4 import BeautifulSoup
    from .models import YoutubeVideo, News, TelegramMessage, StockQuestionReport, StockUploadedReport, SystemSetting

    stock = get_object_or_404(Info, code=code)

    # 저장된 데이터 타입 가져오기
    try:
        saved_types = SystemSetting.objects.get(key='valuation_data_types').value
        data_types = [t for t in saved_types.split(',') if t]
        if not data_types:
            data_types = ['analysis', 'key_briefing', 'nodaji', 'report', 'youtube', 'news', 'telegram', 'memo']
    except SystemSetting.DoesNotExist:
        data_types = ['analysis', 'key_briefing', 'nodaji', 'report', 'youtube', 'news', 'telegram', 'memo']

    def html_to_text(html):
        """HTML을 텍스트로 변환"""
        if not html:
            return ''
        soup = BeautifulSoup(html, 'html.parser')
        text = soup.get_text(separator='\n')
        text = re.sub(r'\n\s*\n+', '\n\n', text)
        text = re.sub(r'\[cite_start\]', '', text)
        text = re.sub(r'\[cite_end\]', '', text)
        text = re.sub(r'\[cite:\s*[\d,\s]+\]', '', text)
        text = re.sub(r'\[/cite\]', '', text)
        return text.strip()

    lines = []
    lines.append(f"=== {stock.name} ({stock.code}) 데이터 ===\n")

    if 'key_briefing' in data_types:
        lines.append("## 핵심 브리핑")
        if stock.key_briefing:
            lines.append(stock.key_briefing)
        else:
            lines.append("- 저장된 데이터가 없습니다.")
        lines.append("")

    if 'nodaji' in data_types:
        lines.append("## 노다지 IR노트 (최대 5개)")
        nodaji_list = Nodaji.objects.filter(
            stock=stock,
            title__contains=stock.name
        ).exclude(summary__isnull=True).exclude(summary='').order_by('-date')[:5]
        if nodaji_list:
            for n in nodaji_list:
                date_str = n.date.strftime('%Y-%m-%d') if n.date else '-'
                lines.append(f"\n### [{date_str}] {n.title}")
                if n.summary:
                    summary = html_to_text(n.summary)
                    lines.append(f"요약:\n{summary}")
        else:
            lines.append("- 저장된 데이터가 없습니다.")
        lines.append("")

    if 'report' in data_types:
        lines.append("## 애널리스트 리포트 (최신 10개)")
        all_reports = Report.objects.filter(stock=stock).order_by('-date')
        seen_dates = set()
        reports = []
        for r in all_reports:
            if r.date not in seen_dates:
                reports.append(r)
                seen_dates.add(r.date)
                if len(reports) >= 10:
                    break
        if reports:
            for r in reports:
                date_str = r.date.strftime('%Y-%m-%d') if r.date else '-'
                lines.append(f"\n### [{date_str}] {r.title}")
                lines.append(f"작성자: {r.author} / 증권사: {r.provider}")
                if r.summary:
                    summary_text = html_to_text(r.summary)
                    lines.append(f"요약:\n{summary_text}")
                else:
                    lines.append("요약: (요약 없음)")
        else:
            lines.append("- 저장된 데이터가 없습니다.")
        lines.append("")

    if 'youtube' in data_types:
        lines.append("## 유튜브 (최대 10개)")
        youtube_list = YoutubeVideo.objects.filter(stock=stock).order_by('-id')[:10]
        if youtube_list:
            for v in youtube_list:
                lines.append(f"\n### {v.title}")
                if v.channel:
                    lines.append(f"채널: {v.channel}")
                if v.summary:
                    summary_text = html_to_text(v.summary)
                    lines.append(f"요약:\n{summary_text}")
                else:
                    lines.append("요약: (요약 없음)")
        else:
            lines.append("- 저장된 데이터가 없습니다.")
        lines.append("")

    if 'news' in data_types:
        lines.append("## 뉴스 (최대 10개)")
        news_list = News.objects.filter(stock=stock).order_by('-id')[:10]
        if news_list:
            for n in news_list:
                lines.append(f"\n### {n.title}")
                if n.summary:
                    summary_text = html_to_text(n.summary)
                    lines.append(f"요약:\n{summary_text}")
                else:
                    lines.append("요약: (요약 없음)")
        else:
            lines.append("- 저장된 데이터가 없습니다.")
        lines.append("")

    if 'telegram' in data_types:
        lines.append("## 텔레그램 (최대 10개)")
        telegram_list = TelegramMessage.objects.filter(stock=stock).order_by('-id')[:10]
        if telegram_list:
            for t in telegram_list:
                channel_name = t.channel_name or t.channel
                lines.append(f"\n### {channel_name}")
                lines.append(t.text[:500] if t.text else '')
                if t.summary:
                    summary_text = html_to_text(t.summary)
                    lines.append(f"요약:\n{summary_text}")
        else:
            lines.append("- 저장된 데이터가 없습니다.")
        lines.append("")

    if 'memo' in data_types:
        lines.append("## 메모")
        if stock.memo:
            lines.append(html_to_text(stock.memo))
        else:
            lines.append("- 저장된 데이터가 없습니다.")
        lines.append("")

    if 'research' in data_types:
        lines.append("## 리서치 (최대 10개)")
        qr_list = StockQuestionReport.objects.filter(stock=stock).order_by('-id')[:10]
        if qr_list:
            for qr in qr_list:
                lines.append(f"\n### Q: {qr.question}")
                if qr.report:
                    if qr.report_type == 'markdown':
                        lines.append(qr.report)
                    else:
                        lines.append(html_to_text(qr.report))
        else:
            lines.append("- 저장된 데이터가 없습니다.")
        lines.append("")

    # 프롬프트 추가 (데이터 뒤에, {종목명} 치환)
    try:
        saved_prompt = SystemSetting.objects.get(key='prompt_valuation').value
        if saved_prompt:
            import re as re_mod
            saved_prompt = re_mod.sub(r'\{종목명[^}]*\}', stock.name, saved_prompt)
            lines.append("\n---\n")
            lines.append(saved_prompt)
    except SystemSetting.DoesNotExist:
        pass

    return JsonResponse({
        'success': True,
        'data': '\n'.join(lines)
    })


def youtube_summary(request, video_id):
    """유튜브 영상 요약 편집 페이지"""
    from .models import YoutubeVideo, SystemSetting
    video = get_object_or_404(YoutubeVideo, id=video_id)

    if request.method == 'POST':
        video.summary = request.POST.get('summary', '')
        video.my_opinion = request.POST.get('my_opinion', '')
        video.save()
        messages.success(request, '요약이 저장되었습니다.')
        return redirect('stocks:youtube_summary', video_id=video_id)

    prompt_summary = SystemSetting.objects.filter(key='prompt_summary').values_list('value', flat=True).first() or ''

    return render(request, 'stocks/youtube_summary.html', {
        'video': video,
        'prompt_summary': prompt_summary,
    })


@require_GET
def fetch_dart_document(request, rcept_no):
    """DART OpenAPI로 공시 본문 조회"""
    import requests
    import zipfile
    import io
    from bs4 import BeautifulSoup

    api_key = config('DART_API_KEY', default='')
    if not api_key:
        return JsonResponse({'error': 'DART_API_KEY가 설정되지 않았습니다.'}, status=500)

    resp = requests.get(
        'https://opendart.fss.or.kr/api/document.xml',
        params={'crtfc_key': api_key, 'rcept_no': rcept_no},
        timeout=60,
    )
    if resp.status_code != 200:
        return JsonResponse({'error': f'문서 다운로드 실패: {resp.status_code}'}, status=500)

    # ZIP이 아닌 경우 (에러 XML 응답)
    content_type = resp.headers.get('Content-Type', '')
    if 'xml' in content_type or 'text' in content_type:
        return JsonResponse({'error': 'DART API 에러', 'detail': resp.text[:500]}, status=500)

    try:
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
    except Exception as e:
        return JsonResponse({'error': f'ZIP 오류: {e}'}, status=500)

    # 모든 파일에서 텍스트 추출
    all_text = []
    for fname in zf.namelist():
        raw = zf.read(fname)
        text = None
        for enc in ['utf-8', 'euc-kr', 'cp949']:
            try:
                text = raw.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        if not text:
            continue

        soup = BeautifulSoup(text, 'html.parser')
        body = soup.find('body')
        if body:
            plain = body.get_text(separator='\n', strip=True)
        else:
            plain = soup.get_text(separator='\n', strip=True)

        if plain:
            # 연속 빈줄 정리
            import re as _re2
            plain = _re2.sub(r'\n{3,}', '\n\n', plain)
            all_text.append(plain)

    if not all_text:
        return JsonResponse({'error': '문서 내용을 추출할 수 없습니다.'}, status=404)

    content = '\n\n---\n\n'.join(all_text)
    return JsonResponse({
        'success': True,
        'rcept_no': rcept_no,
        'content_length': len(content),
        'content': content,
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


def sector(request):
    """섹터 페이지"""
    from .models import Sector, CustomSector
    from django.db.models import Count

    # 사용자 정의 섹터 (컨텐츠 수 포함)
    custom_sectors = CustomSector.objects.annotate(
        total_stock_count=Count('stocks', distinct=True) + Count('etfs', distinct=True),
        diary_count=Count('diaries', distinct=True),
        event_count=Count('events', distinct=True),
        research_count=Count('question_reports', distinct=True),
        report_count=Count('uploaded_reports', distinct=True),
        telegram_count=Count('telegram_messages', distinct=True),
        news_count=Count('news_articles', distinct=True),
        youtube_count=Count('youtube_videos', distinct=True),
    )

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
        'custom_sectors': custom_sectors,
    }
    return render(request, 'stocks/sector.html', context)


def sector_detail(request, sector_id):
    """섹터 상세 페이지"""
    from .models import CustomSector, SectorTelegramMessage, SectorNews, SectorYoutubeVideo, SectorQuestionReport, SectorUploadedReport, Info, InfoETF
    from itertools import chain

    sector = get_object_or_404(CustomSector, id=sector_id)

    # 업로드된 리포트
    uploaded_reports = SectorUploadedReport.objects.filter(sector=sector).order_by('-created_at')

    # 해당 섹터에 연결된 종목과 ETF
    related_stocks = Info.objects.filter(custom_sectors=sector).order_by('name')
    related_etfs = InfoETF.objects.filter(custom_sectors=sector).order_by('name')

    # 질문-리포트 목록
    question_reports = SectorQuestionReport.objects.filter(sector=sector)

    # 텔레그램, 뉴스, 유튜브 통합 리스트 (최신순)
    telegram_messages = SectorTelegramMessage.objects.filter(sector=sector).order_by('-date', '-time')
    def parse_sector_news_date(news):
        try:
            pub = (news.published or '').strip()
            date_part = pub.split(' ')[0] if pub else ''
            if date_part:
                parts = date_part.split('-')
                if len(parts) == 3:
                    return (int(parts[0]), int(parts[1]), int(parts[2]))
            return (0, 0, 0)
        except:
            return (0, 0, 0)
    news_articles = sorted(SectorNews.objects.filter(sector=sector), key=parse_sector_news_date, reverse=True)
    import re as re_sector_yt
    def parse_sector_youtube_date(video):
        """유튜브 날짜를 정렬용 타임스탬프로 변환"""
        try:
            pub = (video.published or '').strip()
            if not pub:
                return video.created_at.timestamp() if video.created_at else 0
            now = datetime.now()
            # "3일 전", "2시간 전" 등 상대 날짜 처리
            match = re_sector_yt.search(r'(\d+)\s*(초|분|시간|일|주|개월|년)\s*전', pub)
            if match:
                num = int(match.group(1))
                unit = match.group(2)
                if unit == '초':
                    return (now - timedelta(seconds=num)).timestamp()
                elif unit == '분':
                    return (now - timedelta(minutes=num)).timestamp()
                elif unit == '시간':
                    return (now - timedelta(hours=num)).timestamp()
                elif unit == '일':
                    return (now - timedelta(days=num)).timestamp()
                elif unit == '주':
                    return (now - timedelta(weeks=num)).timestamp()
                elif unit == '개월':
                    return (now - timedelta(days=num*30)).timestamp()
                elif unit == '년':
                    return (now - timedelta(days=num*365)).timestamp()
            # "2025. 10. 22." 또는 "2025.10.22" 형식 (점 구분)
            dot_match = re_sector_yt.search(r'(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})', pub)
            if dot_match:
                return datetime(int(dot_match.group(1)), int(dot_match.group(2)), int(dot_match.group(3))).timestamp()
            # "2025-10-22" 형식 (하이픈 구분)
            dash_match = re_sector_yt.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', pub)
            if dash_match:
                return datetime(int(dash_match.group(1)), int(dash_match.group(2)), int(dash_match.group(3))).timestamp()
            return video.created_at.timestamp() if video.created_at else 0
        except:
            return video.created_at.timestamp() if video.created_at else 0
    youtube_videos = sorted(SectorYoutubeVideo.objects.filter(sector=sector), key=parse_sector_youtube_date, reverse=True)

    # 통합 리스트 생성
    all_items = []
    for msg in telegram_messages:
        all_items.append({
            'type': 'telegram',
            'icon': '💬',
            'date': msg.date,
            'time': msg.time,
            'title': msg.text[:100] + '...' if len(msg.text) > 100 else msg.text,
            'source': msg.channel_name or msg.channel,
            'link': None,
            'summary_url': None,
        })
    for news in news_articles:
        all_items.append({
            'type': 'news',
            'icon': '📰',
            'date': news.published or '',
            'time': '',
            'title': news.title,
            'source': news.source or '',
            'link': news.link,
            'summary_url': f'/sector/news/{news.id}/summary/' if news.summary else None,
            'has_summary': bool(news.summary),
        })
    for video in youtube_videos:
        all_items.append({
            'type': 'youtube',
            'icon': '🎬',
            'date': video.published or '',
            'time': '',
            'title': video.title,
            'source': video.channel or '',
            'link': video.link,
            'summary_url': f'/sector/youtube/{video.id}/summary/' if video.summary else None,
            'has_summary': bool(video.summary),
        })

    # 날짜+시간 기준 정렬 (최신순)
    def sort_key(item):
        date_str = item['date'] or ''
        time_str = item['time'] or ''
        return (date_str, time_str)

    all_items.sort(key=sort_key, reverse=True)

    # 처음 20건만 표시, 나머지는 더보기로
    initial_items = all_items[:20]
    remaining_items = all_items[20:]

    from .models import SystemSetting
    context = {
        'sector': sector,
        'related_stocks': related_stocks,
        'related_etfs': related_etfs,
        'question_reports': question_reports,
        'initial_items': initial_items,
        'remaining_items': remaining_items,
        'total_count': len(all_items),
        # 탭용 데이터
        'telegram_messages': telegram_messages,
        'news_articles': news_articles,
        'youtube_videos': youtube_videos,
        'uploaded_reports': uploaded_reports,
        'saved_prompts': {s.key: s.value for s in SystemSetting.objects.filter(key__startswith='prompt_')},
    }
    return render(request, 'stocks/sector_detail.html', context)


def sector_edit(request, sector_id):
    """섹터 편집 페이지"""
    from .models import CustomSector, SectorTelegramMessage, SectorNews, SectorYoutubeVideo, SectorQuestionReport, SectorUploadedReport

    sector = get_object_or_404(CustomSector, id=sector_id)

    # POST 처리 (기본정보 저장)
    if request.method == 'POST' and request.POST.get('form_type') == 'info':
        sector.memo = request.POST.get('memo', '').strip()
        sector.basic_report = request.POST.get('basic_report', '')  # HTML이므로 strip 안함
        sector.save()
        messages.success(request, f'{sector.name} 정보가 저장되었습니다.')
        return redirect('stocks:sector_edit', sector_id=sector_id)

    telegram_messages = SectorTelegramMessage.objects.filter(sector=sector).order_by('-date', '-time')
    def parse_sector_news_date_edit(news):
        try:
            pub = (news.published or '').strip()
            date_part = pub.split(' ')[0] if pub else ''
            if date_part:
                parts = date_part.split('-')
                if len(parts) == 3:
                    return (int(parts[0]), int(parts[1]), int(parts[2]))
            return (0, 0, 0)
        except:
            return (0, 0, 0)
    news_articles = sorted(SectorNews.objects.filter(sector=sector), key=parse_sector_news_date_edit, reverse=True)
    import re as re_sector_yt_edit
    def parse_sector_youtube_date_edit(video):
        """유튜브 날짜를 정렬용 타임스탬프로 변환"""
        try:
            pub = (video.published or '').strip()
            if not pub:
                return video.created_at.timestamp() if video.created_at else 0
            now = datetime.now()
            # "3일 전", "2시간 전" 등 상대 날짜 처리
            match = re_sector_yt_edit.search(r'(\d+)\s*(초|분|시간|일|주|개월|년)\s*전', pub)
            if match:
                num = int(match.group(1))
                unit = match.group(2)
                if unit == '초':
                    return (now - timedelta(seconds=num)).timestamp()
                elif unit == '분':
                    return (now - timedelta(minutes=num)).timestamp()
                elif unit == '시간':
                    return (now - timedelta(hours=num)).timestamp()
                elif unit == '일':
                    return (now - timedelta(days=num)).timestamp()
                elif unit == '주':
                    return (now - timedelta(weeks=num)).timestamp()
                elif unit == '개월':
                    return (now - timedelta(days=num*30)).timestamp()
                elif unit == '년':
                    return (now - timedelta(days=num*365)).timestamp()
            # "2025. 10. 22." 또는 "2025.10.22" 형식 (점 구분)
            dot_match = re_sector_yt_edit.search(r'(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})', pub)
            if dot_match:
                return datetime(int(dot_match.group(1)), int(dot_match.group(2)), int(dot_match.group(3))).timestamp()
            # "2025-10-22" 형식 (하이픈 구분)
            dash_match = re_sector_yt_edit.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', pub)
            if dash_match:
                return datetime(int(dash_match.group(1)), int(dash_match.group(2)), int(dash_match.group(3))).timestamp()
            return video.created_at.timestamp() if video.created_at else 0
        except:
            return video.created_at.timestamp() if video.created_at else 0
    youtube_videos = sorted(SectorYoutubeVideo.objects.filter(sector=sector), key=parse_sector_youtube_date_edit, reverse=True)
    question_reports = SectorQuestionReport.objects.filter(sector=sector).order_by('-created_at')
    uploaded_reports = SectorUploadedReport.objects.filter(sector=sector).order_by('-created_at')

    # 저장된 프롬프트 가져오기
    from .models import SystemSetting
    saved_prompts = {}
    for setting in SystemSetting.objects.filter(key__startswith='prompt_'):
        saved_prompts[setting.key] = setting.value

    context = {
        'sector': sector,
        'telegram_messages': telegram_messages,
        'news_articles': news_articles,
        'youtube_videos': youtube_videos,
        'question_reports': question_reports,
        'uploaded_reports': uploaded_reports,
        'saved_prompts': saved_prompts,
    }
    return render(request, 'stocks/sector_edit.html', context)


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
    from .models import ThemeCategory, ExcludedYoutubeChannel, PreferredYoutubeChannel, SystemSetting, CustomSector

    categories = ThemeCategory.objects.prefetch_related('themes').all()
    excluded_channels = ExcludedYoutubeChannel.objects.all()
    preferred_channels = PreferredYoutubeChannel.objects.all()
    custom_sectors = CustomSector.objects.all()

    # 저장된 프롬프트 불러오기
    saved_prompts = {}
    for setting in SystemSetting.objects.filter(key__startswith='prompt_'):
        saved_prompts[setting.key] = setting.value

    # 핵심브리핑 데이터 타입 불러오기
    try:
        saved_types = SystemSetting.objects.get(key='briefing_data_types').value
        briefing_data_types = [t for t in saved_types.split(',') if t]  # 빈 문자열 제거
        if not briefing_data_types:
            briefing_data_types = ['analysis', 'key_briefing', 'nodaji', 'report', 'youtube', 'news', 'telegram', 'memo']
    except SystemSetting.DoesNotExist:
        # 기본값: 모든 타입 선택
        briefing_data_types = ['analysis', 'key_briefing', 'nodaji', 'report', 'youtube', 'news', 'telegram', 'memo']

    context = {
        'categories': categories,
        'excluded_channels': excluded_channels,
        'preferred_channels': preferred_channels,
        'custom_sectors': custom_sectors,
        'saved_prompts': saved_prompts,
        'briefing_data_types': briefing_data_types,
        'telegram_channels': {str(k): v for k, v in TELEGRAM_CHANNELS.items()},
    }
    return render(request, 'stocks/settings.html', context)


def etf(request):
    """ETF 페이지"""
    from .models import InfoETF, DailyChartETF

    # 관심 ETF 목록 (is_active=True) - 섹터명 기준 정렬, 섹터 없는 ETF는 맨 뒤로
    etfs = list(InfoETF.objects.filter(is_active=True).prefetch_related('custom_sectors'))
    etfs.sort(key=lambda e: (
        e.custom_sectors.first().name if e.custom_sectors.exists() else 'ㅎㅎㅎ',  # 섹터명 (없으면 맨 뒤)
        e.name  # 같은 섹터 내에서는 ETF명 순
    ))

    # 모든 ETF의 250일 데이터를 미리 가져옴
    etf_daily_data_cache = {}
    for etf_item in etfs:
        daily_data = list(DailyChartETF.objects.filter(
            etf=etf_item
        ).order_by('-date')[:250])
        etf_daily_data_cache[etf_item.code] = daily_data

    # ============ 현황 테이블 ============
    status_etfs = []
    for etf_item in etfs:
        daily_data = etf_daily_data_cache.get(etf_item.code, [])
        if not daily_data:
            status_etfs.append({
                'etf': etf_item, 'ma_align': '', 'vol_high_20': False, 'vol_high_60': False,
                'is_bullish': True, 'pullback': None, 'pullback_label': '',
            })
            continue

        today = daily_data[0]
        today_vol = today.trading_volume or 0

        max_vol_20 = max((d.trading_volume or 0) for d in daily_data[:20]) if len(daily_data) >= 2 else 0
        max_vol_60 = max((d.trading_volume or 0) for d in daily_data[:60]) if len(daily_data) >= 2 else 0

        # 배열 판단
        ma_align = ''
        if len(daily_data) >= 125:
            ma5 = sum(d.closing_price for d in daily_data[:5]) / 5
            ma20 = sum(d.closing_price for d in daily_data[:20]) / 20
            ma60 = sum(d.closing_price for d in daily_data[:60]) / 60
            ma120 = sum(d.closing_price for d in daily_data[:120]) / 120
            ma120_prev = sum(d.closing_price for d in daily_data[5:125]) / 120
            m = 1.005
            if (ma5 > ma20 * m and ma20 > ma60 * m and ma60 > ma120 * m
                    and ma120 > ma120_prev):
                ma_align = 'bull'
            elif (ma5 * m < ma20 and ma20 * m < ma60 and ma60 * m < ma120
                  and ma120 < ma120_prev):
                ma_align = 'bear'
            else:
                ma_align = 'mixed'

        # 눌림목 판단 (정배열일 때만)
        pullback = None
        pullback_label = ''
        if ma_align == 'bull' and len(daily_data) >= 20:
            _ma20 = sum(d.closing_price for d in daily_data[:20]) / 20
            gap_pct = round((today.closing_price - _ma20) / _ma20 * 100, 1)
            pullback = gap_pct
            if gap_pct > 5:
                pullback_label = '과열'
            elif gap_pct > 2:
                pullback_label = '추세중'
            elif gap_pct > -2:
                pullback_label = '얕은눌림'
            elif gap_pct > -5:
                pullback_label = '깊은눌림'
            else:
                pullback_label = '이탈'

        # 매수/매도 범위 판단
        in_buy_zone = etf_item.current_price and etf_item.buy_price and etf_item.current_price <= etf_item.buy_price
        in_sell_zone = etf_item.current_price and etf_item.sell_price and etf_item.current_price >= etf_item.sell_price

        status_etfs.append({
            'etf': etf_item,
            'ma_align': ma_align,
            'vol_high_20': today_vol > 0 and today_vol >= max_vol_20,
            'vol_high_60': today_vol > 0 and today_vol >= max_vol_60,
            'is_bullish': today.closing_price >= today.opening_price if today.opening_price else True,
            'pullback': pullback,
            'pullback_label': pullback_label,
            'in_buy_zone': in_buy_zone,
            'in_sell_zone': in_sell_zone,
        })

    context = {
        'etfs': etfs,
        'status_etfs': status_etfs,
    }
    return render(request, 'stocks/etf.html', context)


def etf_detail(request, code):
    """ETF 상세 페이지"""
    from .models import InfoETF, DailyChartETF, WeeklyChartETF, MonthlyChartETF, CustomSector

    etf = get_object_or_404(InfoETF.objects.prefetch_related('custom_sectors'), code=code)

    # POST 처리 - 관심섹터 및 보유 여부 저장
    if request.method == 'POST':
        sector_ids = request.POST.getlist('custom_sectors')
        etf.custom_sectors.set(CustomSector.objects.filter(id__in=sector_ids))
        etf.is_holding = request.POST.get('is_holding') == 'on'
        etf.save(update_fields=['is_holding'])
        from django.contrib import messages
        messages.success(request, '저장되었습니다.')
        return redirect('stocks:etf_detail', code=code)

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

    # 관심섹터 전체 목록
    custom_sectors = CustomSector.objects.all()

    # 이평선 값 계산 (매수가 버튼용) - daily_charts는 이미 reverse된 상태(오래된→최신)
    ma10_value = ''
    ma20_value = ''
    ma60_value = ''
    if daily_charts:
        recent = list(reversed(daily_charts))  # 최신→오래된 순으로 변환
        if len(recent) >= 10:
            ma10_value = round(sum(d.closing_price for d in recent[:10]) / 10)
        if len(recent) >= 20:
            ma20_value = round(sum(d.closing_price for d in recent[:20]) / 20)
        if len(recent) >= 60:
            ma60_value = round(sum(d.closing_price for d in recent[:60]) / 60)

    context = {
        'etf': etf,
        'custom_sectors': custom_sectors,
        'daily_candle_data': json.dumps(daily_candle_data),
        'daily_volume_data': json.dumps(daily_volume_data),
        'weekly_candle_data': json.dumps(weekly_candle_data),
        'weekly_volume_data': json.dumps(weekly_volume_data),
        'monthly_candle_data': json.dumps(monthly_candle_data),
        'monthly_volume_data': json.dumps(monthly_volume_data),
        'ma10_value': ma10_value,
        'ma20_value': ma20_value,
        'ma60_value': ma60_value,
    }
    return render(request, 'stocks/etf_detail.html', context)


# ===== ETF 메모/매매근거/투자일지/이벤트 API =====

@require_POST
def etf_memo_save(request, code):
    """ETF 메모 저장 API"""
    from datetime import date
    from .models import InfoETF
    etf = get_object_or_404(InfoETF, code=code)
    memo = request.POST.get('memo', '').strip()
    if memo != (etf.memo or '').strip():
        etf.memo = memo
        etf.memo_updated_at = date.today()
        etf.save(update_fields=['memo', 'memo_updated_at'])
    return JsonResponse({'success': True, 'updated_at': etf.memo_updated_at.strftime('%Y-%m-%d') if etf.memo_updated_at else ''})


@require_POST
def etf_trade_save(request, code):
    """ETF 매매근거 저장 API"""
    from datetime import date
    from .models import InfoETF
    etf = get_object_or_404(InfoETF, code=code)
    changed = False

    buy_reason = request.POST.get('buy_reason')
    if buy_reason is not None and buy_reason.strip() != (etf.buy_reason or '').strip():
        etf.buy_reason = buy_reason.strip()
        changed = True

    sell_reason = request.POST.get('sell_reason')
    if sell_reason is not None and sell_reason.strip() != (etf.sell_reason or '').strip():
        etf.sell_reason = sell_reason.strip()
        changed = True

    buy_price = request.POST.get('buy_price', '').strip()
    new_buy = int(buy_price) if buy_price else None
    if new_buy != etf.buy_price:
        etf.buy_price = new_buy
        changed = True

    sell_price = request.POST.get('sell_price', '').strip()
    new_sell = int(sell_price) if sell_price else None
    if new_sell != etf.sell_price:
        etf.sell_price = new_sell
        changed = True

    if changed:
        etf.trade_updated_at = date.today()
        etf.save(update_fields=['buy_reason', 'sell_reason', 'buy_price', 'sell_price', 'trade_updated_at'])

    return JsonResponse({'success': True, 'updated_at': etf.trade_updated_at.strftime('%Y-%m-%d') if etf.trade_updated_at else ''})


@require_GET
def etf_diary_list(request, code):
    """ETF 투자일지 목록 API"""
    from .models import ETFDiary
    limit = int(request.GET.get('limit', 20))
    offset = int(request.GET.get('offset', 0))
    total = ETFDiary.objects.filter(etf_id=code).count()
    entries = ETFDiary.objects.filter(etf_id=code)[offset:offset + limit]
    results = [{'id': e.id, 'date': e.date.strftime('%Y-%m-%d'), 'content': e.content, 'updated_at': e.updated_at.strftime('%Y-%m-%d %H:%M')} for e in entries]
    return JsonResponse({'success': True, 'results': results, 'total': total, 'has_more': offset + limit < total})


@require_POST
def etf_diary_save(request, code):
    """ETF 투자일지 저장 API"""
    from .models import InfoETF, ETFDiary
    date_str = request.POST.get('date', '').strip()
    content = request.POST.get('content', '').strip()
    if not date_str or not content:
        return JsonResponse({'error': '날짜와 내용을 입력하세요.'}, status=400)
    try:
        date_val = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': '올바른 날짜 형식이 아닙니다.'}, status=400)
    etf = get_object_or_404(InfoETF, code=code)
    if ETFDiary.objects.filter(etf=etf, date=date_val).exists():
        return JsonResponse({'error': '해당 날짜에 이미 일지가 있습니다.'}, status=400)
    entry = ETFDiary.objects.create(etf=etf, date=date_val, content=content)
    return JsonResponse({'success': True, 'id': entry.id})


@require_POST
def etf_diary_update(request, code, diary_id):
    """ETF 투자일지 수정 API"""
    from .models import ETFDiary
    entry = get_object_or_404(ETFDiary, id=diary_id, etf_id=code)
    content = request.POST.get('content', '').strip()
    date_str = request.POST.get('date', '').strip()
    if not content:
        return JsonResponse({'error': '내용을 입력하세요.'}, status=400)
    if date_str:
        try:
            new_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            if new_date != entry.date and ETFDiary.objects.filter(etf_id=code, date=new_date).exists():
                return JsonResponse({'error': '해당 날짜에 이미 일지가 있습니다.'}, status=400)
            entry.date = new_date
        except ValueError:
            pass
    entry.content = content
    entry.save()
    return JsonResponse({'success': True})


@require_POST
def etf_diary_delete(request, code, diary_id):
    """ETF 투자일지 삭제 API"""
    from .models import ETFDiary
    entry = get_object_or_404(ETFDiary, id=diary_id, etf_id=code)
    entry.delete()
    return JsonResponse({'success': True})


@require_GET
def etf_event_list(request, code):
    """ETF 이벤트 목록 API"""
    from .models import ETFEvent
    from datetime import date
    events = ETFEvent.objects.filter(etf_id=code)
    today = date.today()
    results = []
    for ev in events:
        d_day = (ev.date - today).days if ev.date else None
        results.append({'id': ev.id, 'date': ev.date.strftime('%Y-%m-%d') if ev.date else None, 'date_text': ev.date_text, 'title': ev.title, 'content': ev.content, 'd_day': d_day})
    return JsonResponse({'success': True, 'results': results})


@require_POST
def etf_event_save(request, code):
    """ETF 이벤트 저장 API"""
    from .models import InfoETF, ETFEvent
    date_str = request.POST.get('date', '').strip()
    date_text = request.POST.get('date_text', '').strip()
    title = request.POST.get('title', '').strip()
    content = request.POST.get('content', '').strip()
    if not title:
        return JsonResponse({'error': '제목을 입력하세요.'}, status=400)
    if not date_text:
        return JsonResponse({'error': '날짜를 입력하세요.'}, status=400)
    date_val = None
    if date_str:
        try:
            date_val = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    etf = get_object_or_404(InfoETF, code=code)
    max_order = ETFEvent.objects.filter(etf=etf).order_by('-order').values_list('order', flat=True).first()
    ev = ETFEvent.objects.create(etf=etf, date=date_val, date_text=date_text, title=title, content=content, order=(max_order or 0) + 1)
    return JsonResponse({'success': True, 'id': ev.id})


@require_POST
def etf_event_update(request, code, event_id):
    """ETF 이벤트 수정 API"""
    from .models import ETFEvent
    ev = get_object_or_404(ETFEvent, id=event_id, etf_id=code)
    date_str = request.POST.get('date', '').strip()
    date_text = request.POST.get('date_text', '').strip()
    title = request.POST.get('title', '').strip()
    content = request.POST.get('content', '').strip()
    if not title:
        return JsonResponse({'error': '제목을 입력하세요.'}, status=400)
    if not date_text:
        return JsonResponse({'error': '날짜를 입력하세요.'}, status=400)
    ev.date = None
    if date_str:
        try:
            ev.date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    ev.date_text = date_text
    ev.title = title
    ev.content = content
    ev.save()
    return JsonResponse({'success': True})


@require_POST
def etf_event_delete(request, code, event_id):
    """ETF 이벤트 삭제 API"""
    from .models import ETFEvent
    ev = get_object_or_404(ETFEvent, id=event_id, etf_id=code)
    ev.delete()
    return JsonResponse({'success': True})


@require_POST
def etf_event_move(request, code, event_id):
    """ETF 이벤트 순서 이동 API"""
    from .models import ETFEvent
    direction = request.POST.get('direction', '')
    events = list(ETFEvent.objects.filter(etf_id=code))
    idx = next((i for i, e in enumerate(events) if e.id == event_id), None)
    if idx is None:
        return JsonResponse({'error': '이벤트를 찾을 수 없습니다.'}, status=404)
    if direction == 'up' and idx > 0:
        events[idx], events[idx - 1] = events[idx - 1], events[idx]
    elif direction == 'down' and idx < len(events) - 1:
        events[idx], events[idx + 1] = events[idx + 1], events[idx]
    for i, ev in enumerate(events):
        if ev.order != i:
            ETFEvent.objects.filter(id=ev.id).update(order=i)
    return JsonResponse({'success': True})


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
def delete_etf(request, code):
    """ETF 관심종목 삭제 API"""
    from .models import InfoETF, DailyChartETF, WeeklyChartETF, MonthlyChartETF

    etf = get_object_or_404(InfoETF, code=code)

    # 차트 데이터 삭제
    DailyChartETF.objects.filter(etf=etf).delete()
    WeeklyChartETF.objects.filter(etf=etf).delete()
    MonthlyChartETF.objects.filter(etf=etf).delete()

    # ETF 삭제
    etf.delete()

    return JsonResponse({'success': True})


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
def custom_sector_add(request):
    """사용자 정의 섹터 추가 API"""
    from .models import CustomSector

    name = request.POST.get('name', '').strip()

    if not name:
        return JsonResponse({'error': '섹터명을 입력해주세요.'}, status=400)

    if len(name) > 50:
        return JsonResponse({'error': '섹터명은 50자 이하로 입력해주세요.'}, status=400)

    if CustomSector.objects.filter(name=name).exists():
        return JsonResponse({'error': '이미 존재하는 섹터입니다.'}, status=400)

    sector = CustomSector.objects.create(name=name)

    return JsonResponse({
        'success': True,
        'id': sector.id,
        'name': sector.name,
    })


@require_POST
def custom_sector_delete(request, sector_id):
    """사용자 정의 섹터 삭제 API"""
    from .models import CustomSector

    sector = get_object_or_404(CustomSector, id=sector_id)
    sector.delete()

    return JsonResponse({'success': True})


@require_GET
def custom_sector_search(request):
    """관심섹터 검색 API"""
    from .models import CustomSector

    query = request.GET.get('q', '').strip()

    if query:
        sectors = CustomSector.objects.filter(name__icontains=query).order_by('name')
    else:
        sectors = CustomSector.objects.all().order_by('name')

    return JsonResponse({
        'success': True,
        'sectors': [{'id': s.id, 'name': s.name} for s in sectors]
    })


@require_GET
def custom_sector_basic_report(request, sector_id):
    """관심섹터 기초리포트 조회 API"""
    from .models import CustomSector

    sector = get_object_or_404(CustomSector, id=sector_id)

    return JsonResponse({
        'success': True,
        'sector_name': sector.name,
        'basic_report': sector.basic_report or ''
    })


@require_GET
def custom_sector_integrated_report(request, sector_id):
    """관심섹터 기초리포트 조회 API (STEP4용 - 이름 유지)"""
    from .models import CustomSector

    sector = get_object_or_404(CustomSector, id=sector_id)

    if sector.basic_report:
        return JsonResponse({
            'success': True,
            'sector_name': sector.name,
            'report': sector.basic_report,
            'report_type': '기초리포트'
        })
    else:
        return JsonResponse({
            'success': False,
            'sector_name': sector.name,
            'report': '',
            'report_type': ''
        })


@require_POST
def sector_question_report_save(request):
    """섹터 질문리포트 저장 API"""
    from .models import CustomSector, SectorQuestionReport

    sector_id = request.POST.get('sector_id', '')
    question = request.POST.get('question', '').strip()
    report = request.POST.get('report', '')
    report_type = request.POST.get('report_type', 'html')

    if not sector_id:
        return JsonResponse({'success': False, 'error': '섹터를 선택해주세요.'})

    if not question:
        return JsonResponse({'success': False, 'error': '질문을 입력해주세요.'})

    # report_type 유효성 검사
    if report_type not in ('html', 'markdown'):
        report_type = 'html'

    try:
        sector = CustomSector.objects.get(id=sector_id)
    except CustomSector.DoesNotExist:
        return JsonResponse({'success': False, 'error': '섹터를 찾을 수 없습니다.'})

    qr = SectorQuestionReport.objects.create(
        sector=sector,
        question=question,
        report=report,
        report_type=report_type
    )

    return JsonResponse({
        'success': True,
        'id': qr.id,
        'report_type': qr.report_type,
        'message': '질문리포트가 저장되었습니다.'
    })


@require_POST
def sector_question_report_delete(request, report_id):
    """섹터 질문리포트 삭제 API"""
    from .models import SectorQuestionReport

    try:
        qr = SectorQuestionReport.objects.get(id=report_id)
        qr.delete()
        return JsonResponse({'success': True})
    except SectorQuestionReport.DoesNotExist:
        return JsonResponse({'success': False, 'error': '질문리포트를 찾을 수 없습니다.'})


@require_POST
def sector_question_report_update(request, report_id):
    """섹터 질문리포트 수정 API"""
    from .models import SectorQuestionReport

    question = request.POST.get('question', '').strip()
    report = request.POST.get('report', '')
    report_type = request.POST.get('report_type', None)

    if not question:
        return JsonResponse({'success': False, 'error': '질문을 입력해주세요.'})

    try:
        qr = SectorQuestionReport.objects.get(id=report_id)
        qr.question = question
        qr.report = report
        if report_type in ('html', 'markdown'):
            qr.report_type = report_type
        qr.save()
        return JsonResponse({'success': True})
    except SectorQuestionReport.DoesNotExist:
        return JsonResponse({'success': False, 'error': '질문리포트를 찾을 수 없습니다.'})


# ===== 섹터 투자일지 =====

@require_GET
def sector_diary_list(request, sector_id):
    """섹터 투자일지 목록 API"""
    from .models import SectorDiary
    limit = int(request.GET.get('limit', 20))
    offset = int(request.GET.get('offset', 0))
    total = SectorDiary.objects.filter(sector_id=sector_id).count()
    entries = SectorDiary.objects.filter(sector_id=sector_id)[offset:offset + limit]
    results = []
    for entry in entries:
        results.append({
            'id': entry.id,
            'date': entry.date.strftime('%Y-%m-%d'),
            'content': entry.content,
            'updated_at': entry.updated_at.strftime('%Y-%m-%d %H:%M'),
        })
    return JsonResponse({'success': True, 'results': results, 'total': total, 'has_more': offset + limit < total})


@require_POST
def sector_diary_save(request, sector_id):
    """섹터 투자일지 저장 API"""
    from .models import SectorDiary, CustomSector
    date_str = request.POST.get('date', '').strip()
    content = request.POST.get('content', '').strip()
    if not date_str or not content:
        return JsonResponse({'error': '날짜와 내용을 입력하세요.'}, status=400)
    try:
        date_val = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': '올바른 날짜 형식이 아닙니다.'}, status=400)
    sector = get_object_or_404(CustomSector, id=sector_id)
    if SectorDiary.objects.filter(sector=sector, date=date_val).exists():
        return JsonResponse({'error': '해당 날짜에 이미 일지가 있습니다.'}, status=400)
    entry = SectorDiary.objects.create(sector=sector, date=date_val, content=content)
    return JsonResponse({'success': True, 'id': entry.id})


@require_POST
def sector_diary_update(request, sector_id, diary_id):
    """섹터 투자일지 수정 API"""
    from .models import SectorDiary
    entry = get_object_or_404(SectorDiary, id=diary_id, sector_id=sector_id)
    content = request.POST.get('content', '').strip()
    date_str = request.POST.get('date', '').strip()
    if not content:
        return JsonResponse({'error': '내용을 입력하세요.'}, status=400)
    if date_str:
        try:
            new_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            if new_date != entry.date and SectorDiary.objects.filter(sector_id=sector_id, date=new_date).exists():
                return JsonResponse({'error': '해당 날짜에 이미 일지가 있습니다.'}, status=400)
            entry.date = new_date
        except ValueError:
            pass
    entry.content = content
    entry.save()
    return JsonResponse({'success': True})


@require_POST
def sector_diary_delete(request, sector_id, diary_id):
    """섹터 투자일지 삭제 API"""
    from .models import SectorDiary
    entry = get_object_or_404(SectorDiary, id=diary_id, sector_id=sector_id)
    entry.delete()
    return JsonResponse({'success': True})


@require_POST
def sector_related_add(request, sector_id):
    """섹터에 관련 종목/ETF 추가 API"""
    from .models import CustomSector, Info, InfoETF
    sector = get_object_or_404(CustomSector, id=sector_id)
    code = request.POST.get('code', '').strip()
    item_type = request.POST.get('type', 'stock')
    if not code:
        return JsonResponse({'error': '코드를 입력하세요.'}, status=400)
    if item_type == 'etf':
        obj = InfoETF.objects.filter(code=code).first()
        if not obj:
            return JsonResponse({'error': 'ETF를 찾을 수 없습니다.'}, status=404)
        sector.etfs.add(obj)
        return JsonResponse({'success': True, 'name': obj.name, 'code': obj.code})
    else:
        obj = Info.objects.filter(code=code).first()
        if not obj:
            return JsonResponse({'error': '종목을 찾을 수 없습니다.'}, status=404)
        sector.stocks.add(obj)
        return JsonResponse({'success': True, 'name': obj.name, 'code': obj.code})


@require_POST
def sector_related_remove(request, sector_id):
    """섹터에서 관련 종목/ETF 제거 API"""
    from .models import CustomSector, Info, InfoETF
    sector = get_object_or_404(CustomSector, id=sector_id)
    code = request.POST.get('code', '').strip()
    item_type = request.POST.get('type', 'stock')
    if item_type == 'etf':
        obj = InfoETF.objects.filter(code=code).first()
        if obj:
            sector.etfs.remove(obj)
    else:
        obj = Info.objects.filter(code=code).first()
        if obj:
            sector.stocks.remove(obj)
    return JsonResponse({'success': True})


@require_POST
def sector_memo_save(request, sector_id):
    """섹터 메모 저장 API"""
    from .models import CustomSector
    sector = get_object_or_404(CustomSector, id=sector_id)
    memo = request.POST.get('memo', '').strip()
    sector.memo = memo
    sector.save(update_fields=['memo'])
    return JsonResponse({'success': True})


@require_POST
def sector_trade_save(request, sector_id):
    """섹터 매매근거 저장 API"""
    from .models import CustomSector
    from datetime import date
    sector = get_object_or_404(CustomSector, id=sector_id)
    changed = False
    buy_reason = request.POST.get('buy_reason')
    if buy_reason is not None and buy_reason.strip() != (sector.buy_reason or '').strip():
        sector.buy_reason = buy_reason.strip()
        changed = True
    sell_reason = request.POST.get('sell_reason')
    if sell_reason is not None and sell_reason.strip() != (sector.sell_reason or '').strip():
        sector.sell_reason = sell_reason.strip()
        changed = True
    if changed:
        sector.trade_updated_at = date.today()
        sector.save(update_fields=['buy_reason', 'sell_reason', 'trade_updated_at'])
    return JsonResponse({'success': True, 'updated_at': sector.trade_updated_at.strftime('%Y-%m-%d') if sector.trade_updated_at else ''})


# ===== 섹터 이벤트 =====

@require_GET
def sector_event_list(request, sector_id):
    """섹터 이벤트 목록 API"""
    from .models import SectorEvent
    from datetime import date
    events = SectorEvent.objects.filter(sector_id=sector_id)
    today = date.today()
    results = []
    for ev in events:
        d_day = None
        if ev.date:
            d_day = (ev.date - today).days
        results.append({
            'id': ev.id, 'date': ev.date.strftime('%Y-%m-%d') if ev.date else None,
            'date_text': ev.date_text, 'title': ev.title, 'content': ev.content, 'd_day': d_day,
        })
    return JsonResponse({'success': True, 'results': results})


@require_POST
def sector_event_save(request, sector_id):
    """섹터 이벤트 저장 API"""
    from .models import SectorEvent, CustomSector
    date_str = request.POST.get('date', '').strip()
    date_text = request.POST.get('date_text', '').strip()
    title = request.POST.get('title', '').strip()
    content = request.POST.get('content', '').strip()
    if not title:
        return JsonResponse({'error': '제목을 입력하세요.'}, status=400)
    if not date_text:
        return JsonResponse({'error': '날짜를 입력하세요.'}, status=400)
    date_val = None
    if date_str:
        try:
            date_val = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    sector = get_object_or_404(CustomSector, id=sector_id)
    max_order = SectorEvent.objects.filter(sector=sector).order_by('-order').values_list('order', flat=True).first()
    ev = SectorEvent.objects.create(
        sector=sector, date=date_val, date_text=date_text,
        title=title, content=content, order=(max_order or 0) + 1
    )
    return JsonResponse({'success': True, 'id': ev.id})


@require_POST
def sector_event_update(request, sector_id, event_id):
    """섹터 이벤트 수정 API"""
    from .models import SectorEvent
    ev = get_object_or_404(SectorEvent, id=event_id, sector_id=sector_id)
    date_str = request.POST.get('date', '').strip()
    date_text = request.POST.get('date_text', '').strip()
    title = request.POST.get('title', '').strip()
    content = request.POST.get('content', '').strip()
    if not title:
        return JsonResponse({'error': '제목을 입력하세요.'}, status=400)
    if not date_text:
        return JsonResponse({'error': '날짜를 입력하세요.'}, status=400)
    ev.date = None
    if date_str:
        try:
            ev.date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    ev.date_text = date_text
    ev.title = title
    ev.content = content
    ev.save()
    return JsonResponse({'success': True})


@require_POST
def sector_event_delete(request, sector_id, event_id):
    """섹터 이벤트 삭제 API"""
    from .models import SectorEvent
    ev = get_object_or_404(SectorEvent, id=event_id, sector_id=sector_id)
    ev.delete()
    return JsonResponse({'success': True})


@require_POST
def sector_event_move(request, sector_id, event_id):
    """섹터 이벤트 순서 이동 API"""
    from .models import SectorEvent
    direction = request.POST.get('direction', '')
    events = list(SectorEvent.objects.filter(sector_id=sector_id))
    idx = next((i for i, e in enumerate(events) if e.id == event_id), None)
    if idx is None:
        return JsonResponse({'error': '이벤트를 찾을 수 없습니다.'}, status=404)
    if direction == 'up' and idx > 0:
        events[idx], events[idx - 1] = events[idx - 1], events[idx]
    elif direction == 'down' and idx < len(events) - 1:
        events[idx], events[idx + 1] = events[idx + 1], events[idx]
    for i, ev in enumerate(events):
        if ev.order != i:
            SectorEvent.objects.filter(id=ev.id).update(order=i)
    return JsonResponse({'success': True})


@require_POST
def stock_question_report_save(request):
    """종목 질문리포트 저장 API"""
    from .models import Info, StockQuestionReport

    stock_code = request.POST.get('stock_code', '')
    question = request.POST.get('question', '').strip()
    report = request.POST.get('report', '')
    report_type = request.POST.get('report_type', 'html')

    if not stock_code:
        return JsonResponse({'success': False, 'error': '종목코드가 필요합니다.'})

    if not question:
        return JsonResponse({'success': False, 'error': '질문을 입력해주세요.'})

    # report_type 유효성 검사
    if report_type not in ('html', 'markdown'):
        report_type = 'html'

    try:
        stock = Info.objects.get(code=stock_code)
    except Info.DoesNotExist:
        return JsonResponse({'success': False, 'error': '종목을 찾을 수 없습니다.'})

    qr = StockQuestionReport.objects.create(
        stock=stock,
        question=question,
        report=report,
        report_type=report_type
    )

    return JsonResponse({'success': True, 'id': qr.id, 'report_type': qr.report_type})


@require_POST
def stock_question_report_delete(request, report_id):
    """종목 질문리포트 삭제 API"""
    from .models import StockQuestionReport

    try:
        qr = StockQuestionReport.objects.get(id=report_id)
        qr.delete()
        return JsonResponse({'success': True})
    except StockQuestionReport.DoesNotExist:
        return JsonResponse({'success': False, 'error': '질문리포트를 찾을 수 없습니다.'})


@require_POST
def stock_question_report_update(request, report_id):
    """종목 질문리포트 수정 API"""
    from .models import StockQuestionReport

    question = request.POST.get('question', '').strip()
    report = request.POST.get('report', '')
    report_type = request.POST.get('report_type', None)

    if not question:
        return JsonResponse({'success': False, 'error': '질문을 입력해주세요.'})

    try:
        qr = StockQuestionReport.objects.get(id=report_id)
        qr.question = question
        qr.report = report
        if report_type in ('html', 'markdown'):
            qr.report_type = report_type
        qr.save()
        return JsonResponse({'success': True})
    except StockQuestionReport.DoesNotExist:
        return JsonResponse({'success': False, 'error': '질문리포트를 찾을 수 없습니다.'})


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


@require_POST
def theme_resolve(request):
    """
    '종목명|대분류|중분류' 형식 입력을 받아 ThemeCategory/Theme를 자동 생성하고
    Theme id 목록을 반환. 종목명은 무시. 중분류는 컴마가 있어도 split하지 않고
    하나의 Theme로 저장.

    여러 줄 입력 가능 - 각 줄을 동일 규칙으로 처리.
    """
    from .models import Theme, ThemeCategory

    raw = request.POST.get('text', '').strip()
    if not raw:
        return JsonResponse({'error': '입력값이 비어있습니다.'}, status=400)

    results = []
    errors = []

    for lineno, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue

        parts = [p.strip() for p in line.split('|')]
        if len(parts) < 3:
            errors.append(f'{lineno}행: "종목명|대분류|중분류" 형식이 아닙니다.')
            continue

        # 종목명(parts[0])은 무시
        category_name = parts[1]
        theme_name = '|'.join(parts[2:]).strip()  # 3개 이상 |가 와도 뒤를 통째로

        if not category_name or not theme_name:
            errors.append(f'{lineno}행: 대분류 또는 중분류가 비어있습니다.')
            continue

        if len(category_name) > 20:
            errors.append(f'{lineno}행: 대분류명은 20자 이하여야 합니다.')
            continue

        if len(theme_name) > 100:
            errors.append(f'{lineno}행: 중분류명은 100자 이하여야 합니다.')
            continue

        category, _ = ThemeCategory.objects.get_or_create(name=category_name)
        theme, _ = Theme.objects.get_or_create(category=category, name=theme_name)

        results.append({
            'id': theme.id,
            'category_name': category.name,
            'name': theme.name,
        })

    if not results and errors:
        return JsonResponse({'error': '\n'.join(errors)}, status=400)

    return JsonResponse({
        'success': True,
        'themes': results,
        'errors': errors,
    })


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
                date_str = (item.get('date', '') or '').strip()
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


@require_GET
def search_google(request):
    """Google 웹 검색 API - Playwright 사용"""
    from urllib.parse import quote

    keyword = request.GET.get('keyword', '')
    limit = int(request.GET.get('limit', 5))

    if not keyword:
        return JsonResponse({'error': '검색어가 필요합니다.'}, status=400)

    url = f'https://www.google.com/search?q={quote(keyword)}&hl=ko&gl=KR'

    try:
        from playwright.sync_api import sync_playwright
        from bs4 import BeautifulSoup

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            })
            page.goto(url, wait_until='networkidle', timeout=30000)
            page.wait_for_timeout(2000)

            html = page.content()
            browser.close()

            soup = BeautifulSoup(html, 'html.parser')
            results = []

            # Google 검색 결과 파싱
            for g in soup.select('div.g'):
                # 제목과 링크
                title_el = g.select_one('h3')
                link_el = g.select_one('a[href^="http"]')

                if not title_el or not link_el:
                    continue

                title = title_el.get_text(strip=True)
                link = link_el.get('href', '')

                # 설명
                snippet = ''
                snippet_el = g.select_one('div[data-sncf], div.VwiC3b, span.aCOpRe')
                if snippet_el:
                    snippet = snippet_el.get_text(strip=True)

                if title and link:
                    results.append({
                        'title': title,
                        'link': link,
                        'snippet': snippet,
                    })

                if len(results) >= limit:
                    break

        return JsonResponse({
            'success': True,
            'keyword': keyword,
            'results': results,
        })

    except Exception as e:
        import traceback
        return JsonResponse({'error': str(e), 'trace': traceback.format_exc()}, status=500)


@require_GET
def search_youtube(request):
    """유튜브 검색 API"""
    import requests as http_requests
    import re
    from .models import ExcludedYoutubeChannel

    keyword = request.GET.get('keyword', '')
    limit = int(request.GET.get('limit', 10))
    min_views = int(request.GET.get('min_views', 1000))

    if not keyword:
        return JsonResponse({'error': '검색어가 필요합니다.'}, status=400)

    # 제외 채널 목록 가져오기
    excluded_channels = set(ExcludedYoutubeChannel.objects.values_list('name', flat=True))

    def parse_views(views_text):
        """조회수 텍스트를 숫자로 변환 (예: '조회수 1.2만회' -> 12000)"""
        if not views_text:
            return 0
        # 숫자와 단위 추출
        match = re.search(r'([\d,.]+)\s*(만|천)?', views_text)
        if not match:
            return 0
        num_str = match.group(1).replace(',', '')
        try:
            num = float(num_str)
            unit = match.group(2)
            if unit == '만':
                num *= 10000
            elif unit == '천':
                num *= 1000
            return int(num)
        except:
            return 0

    try:
        from urllib.parse import quote
        # sp=CAI%253D: 업로드 날짜순 정렬 (최신순)
        url = f'https://www.youtube.com/results?search_query={quote(keyword)}&sp=CAI%253D'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'ko-KR,ko;q=0.9',
        }

        response = http_requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        # ytInitialData JSON 추출
        import json
        data = None

        # var ytInitialData = { 시작점 찾기
        start_marker = 'var ytInitialData = '
        start_idx = response.text.find(start_marker)
        if start_idx != -1:
            start_idx += len(start_marker)
            # JSON 끝점 찾기 (중첩 괄호 처리)
            brace_count = 0
            end_idx = start_idx
            for i, char in enumerate(response.text[start_idx:], start_idx):
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end_idx = i + 1
                        break

            if end_idx > start_idx:
                try:
                    json_str = response.text[start_idx:end_idx]
                    data = json.loads(json_str)
                except json.JSONDecodeError:
                    pass

        if not data:
            return JsonResponse({'error': 'YouTube 데이터를 파싱할 수 없습니다.'}, status=500)

        # 비디오 정보 추출
        videos = []
        try:
            contents = data['contents']['twoColumnSearchResultsRenderer']['primaryContents']['sectionListRenderer']['contents'][0]['itemSectionRenderer']['contents']

            for item in contents:
                if 'videoRenderer' not in item:
                    continue

                video = item['videoRenderer']
                video_id = video.get('videoId', '')
                title = video.get('title', {}).get('runs', [{}])[0].get('text', '')
                channel = video.get('ownerText', {}).get('runs', [{}])[0].get('text', '')
                views_text = video.get('viewCountText', {}).get('simpleText', '') or video.get('viewCountText', {}).get('runs', [{}])[0].get('text', '')
                published = video.get('publishedTimeText', {}).get('simpleText', '')
                duration = video.get('lengthText', {}).get('simpleText', '')
                thumbnail = video.get('thumbnail', {}).get('thumbnails', [{}])[-1].get('url', '')

                # 조회수 파싱 및 필터링
                views_num = parse_views(views_text)
                if views_num < min_views:
                    continue

                # 제외 채널 필터링
                if channel in excluded_channels:
                    continue

                if video_id and title:
                    videos.append({
                        'title': title,
                        'link': f'https://www.youtube.com/watch?v={video_id}',
                        'channel': channel,
                        'duration': duration,
                        'views': views_text,
                        'views_num': views_num,
                        'published': published,
                        'thumbnail': thumbnail,
                    })

        except (KeyError, IndexError):
            pass

        return JsonResponse({
            'success': True,
            'keyword': keyword,
            'min_views': min_views,
            'results': videos,
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_POST
def youtube_channel_add(request):
    """유튜브 제외 채널 추가 API"""
    from .models import ExcludedYoutubeChannel

    name = request.POST.get('name', '').strip()

    if not name:
        return JsonResponse({'error': '채널명을 입력해주세요.'}, status=400)

    if len(name) > 100:
        return JsonResponse({'error': '채널명은 100자 이하로 입력해주세요.'}, status=400)

    if ExcludedYoutubeChannel.objects.filter(name=name).exists():
        return JsonResponse({'error': '이미 등록된 채널입니다.'}, status=400)

    channel = ExcludedYoutubeChannel.objects.create(name=name)

    return JsonResponse({
        'success': True,
        'id': channel.id,
        'name': channel.name,
    })


@require_POST
def youtube_channel_delete(request, channel_id):
    """유튜브 제외 채널 삭제 API"""
    from .models import ExcludedYoutubeChannel

    channel = get_object_or_404(ExcludedYoutubeChannel, id=channel_id)
    channel.delete()

    return JsonResponse({'success': True})


@require_POST
def preferred_channel_add(request):
    """유튜브 선호 채널 추가 API"""
    from .models import PreferredYoutubeChannel

    name = request.POST.get('name', '').strip()

    if not name:
        return JsonResponse({'error': '채널명을 입력해주세요.'}, status=400)

    if len(name) > 100:
        return JsonResponse({'error': '채널명은 100자 이하로 입력해주세요.'}, status=400)

    if PreferredYoutubeChannel.objects.filter(name=name).exists():
        return JsonResponse({'error': '이미 등록된 채널입니다.'}, status=400)

    channel = PreferredYoutubeChannel.objects.create(name=name)

    return JsonResponse({
        'success': True,
        'id': channel.id,
        'name': channel.name,
    })


@require_POST
def preferred_channel_delete(request, channel_id):
    """유튜브 선호 채널 삭제 API"""
    from .models import PreferredYoutubeChannel

    channel = get_object_or_404(PreferredYoutubeChannel, id=channel_id)
    channel.delete()

    return JsonResponse({'success': True})


@require_GET
def search_youtube_preferred(request):
    """유튜브 선호 채널 검색 API - 각 선호 채널별로 검색"""
    import requests as http_requests
    import re
    from .models import PreferredYoutubeChannel

    keyword = request.GET.get('keyword', '')
    min_views = int(request.GET.get('min_views', 1000))

    if not keyword:
        return JsonResponse({'error': '검색어가 필요합니다.'}, status=400)

    # 선호 채널 목록 가져오기
    preferred_channels = list(PreferredYoutubeChannel.objects.values_list('name', flat=True))

    if not preferred_channels:
        return JsonResponse({
            'success': True,
            'keyword': keyword,
            'results': [],
            'message': '선호 채널이 등록되어 있지 않습니다. 설정에서 선호 채널을 추가해주세요.'
        })

    def parse_views(views_text):
        """조회수 텍스트를 숫자로 변환 (예: '조회수 1.2만회' -> 12000)"""
        if not views_text:
            return 0
        match = re.search(r'([\d,.]+)\s*(만|천)?', views_text)
        if not match:
            return 0
        num_str = match.group(1).replace(',', '')
        try:
            num = float(num_str)
            unit = match.group(2)
            if unit == '만':
                num *= 10000
            elif unit == '천':
                num *= 1000
            return int(num)
        except:
            return 0

    all_videos = []
    from urllib.parse import quote
    import json

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'ko-KR,ko;q=0.9',
    }

    # 각 선호 채널별로 검색
    for channel_name in preferred_channels:
        try:
            search_query = f'{keyword} {channel_name}'
            # sp=CAI%253D: 업로드 날짜순 정렬 (최신순)
            url = f'https://www.youtube.com/results?search_query={quote(search_query)}&sp=CAI%253D'

            response = http_requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            # ytInitialData JSON 추출
            data = None
            start_marker = 'var ytInitialData = '
            start_idx = response.text.find(start_marker)
            if start_idx != -1:
                start_idx += len(start_marker)
                brace_count = 0
                end_idx = start_idx
                for i, char in enumerate(response.text[start_idx:], start_idx):
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            end_idx = i + 1
                            break

                if end_idx > start_idx:
                    try:
                        json_str = response.text[start_idx:end_idx]
                        data = json.loads(json_str)
                    except json.JSONDecodeError:
                        pass

            if not data:
                continue

            # 비디오 정보 추출
            try:
                contents = data['contents']['twoColumnSearchResultsRenderer']['primaryContents']['sectionListRenderer']['contents'][0]['itemSectionRenderer']['contents']

                for item in contents:
                    if 'videoRenderer' not in item:
                        continue

                    video = item['videoRenderer']
                    video_id = video.get('videoId', '')
                    title = video.get('title', {}).get('runs', [{}])[0].get('text', '')
                    channel = video.get('ownerText', {}).get('runs', [{}])[0].get('text', '')
                    views_text = video.get('viewCountText', {}).get('simpleText', '') or video.get('viewCountText', {}).get('runs', [{}])[0].get('text', '')
                    published = video.get('publishedTimeText', {}).get('simpleText', '')
                    duration = video.get('lengthText', {}).get('simpleText', '')
                    thumbnail = video.get('thumbnail', {}).get('thumbnails', [{}])[-1].get('url', '')

                    # 조회수 파싱 및 필터링
                    views_num = parse_views(views_text)
                    if views_num < min_views:
                        continue

                    if video_id and title:
                        # 중복 체크 (같은 video_id가 이미 있으면 스킵)
                        if not any(v['link'].endswith(video_id) for v in all_videos):
                            all_videos.append({
                                'title': title,
                                'link': f'https://www.youtube.com/watch?v={video_id}',
                                'channel': channel,
                                'duration': duration,
                                'views': views_text,
                                'views_num': views_num,
                                'published': published,
                                'thumbnail': thumbnail,
                            })

            except (KeyError, IndexError):
                pass

        except Exception:
            continue

    # 날짜 파싱 함수 (정렬용)
    def parse_published(text):
        """업로드 시간 텍스트를 정렬용 숫자로 변환"""
        if not text:
            return float('inf')
        # "1시간 전", "2일 전", "3주 전", "1개월 전", "1년 전" 형식 처리
        import re
        match = re.search(r'(\d+)\s*(분|시간|일|주|개월|년)\s*전', text)
        if not match:
            return float('inf')
        num = int(match.group(1))
        unit = match.group(2)
        multipliers = {'분': 1, '시간': 60, '일': 1440, '주': 10080, '개월': 43200, '년': 525600}
        return num * multipliers.get(unit, float('inf'))

    # 최신순으로 정렬
    all_videos.sort(key=lambda x: parse_published(x['published']))

    return JsonResponse({
        'success': True,
        'keyword': keyword,
        'min_views': min_views,
        'channels_searched': preferred_channels,
        'results': all_videos,
    })


@require_POST
def youtube_video_save(request):
    """유튜브 영상 저장 API"""
    from .models import YoutubeVideo, Info

    stock_code = request.POST.get('stock_code', '').strip()
    video_id = request.POST.get('video_id', '').strip()
    title = request.POST.get('title', '').strip()
    channel = request.POST.get('channel', '').strip()
    thumbnail = request.POST.get('thumbnail', '').strip()
    duration = request.POST.get('duration', '').strip()
    views = request.POST.get('views', '').strip()
    published = request.POST.get('published', '').strip()

    if not stock_code or not video_id or not title:
        return JsonResponse({'error': '필수 정보가 누락되었습니다.'}, status=400)

    stock = get_object_or_404(Info, code=stock_code)

    # 이미 저장된 영상인지 확인
    if YoutubeVideo.objects.filter(stock=stock, video_id=video_id).exists():
        return JsonResponse({'error': '이미 저장된 영상입니다.'}, status=400)

    video = YoutubeVideo.objects.create(
        stock=stock,
        video_id=video_id,
        title=title,
        channel=channel,
        thumbnail=thumbnail,
        duration=duration,
        views=views,
        published=published,
    )

    return JsonResponse({
        'success': True,
        'id': video.id,
        'video_id': video.video_id,
        'title': video.title,
    })


@require_POST
def youtube_video_save_by_link(request):
    """유튜브 링크로 영상 저장 API"""
    import requests as http_requests
    import re
    import json
    from .models import YoutubeVideo, Info

    stock_code = request.POST.get('stock_code', '').strip()
    link = request.POST.get('link', '').strip()

    if not stock_code or not link:
        return JsonResponse({'error': '필수 정보가 누락되었습니다.'}, status=400)

    # video_id 추출
    video_id = None
    # youtube.com/watch?v=VIDEO_ID
    match = re.search(r'[?&]v=([^&]+)', link)
    if match:
        video_id = match.group(1)
    else:
        # youtu.be/VIDEO_ID
        match = re.search(r'youtu\.be/([^?&]+)', link)
        if match:
            video_id = match.group(1)
        else:
            # youtube.com/embed/VIDEO_ID
            match = re.search(r'embed/([^?&]+)', link)
            if match:
                video_id = match.group(1)
            else:
                # youtube.com/shorts/VIDEO_ID
                match = re.search(r'shorts/([^?&]+)', link)
                if match:
                    video_id = match.group(1)

    if not video_id:
        return JsonResponse({'error': '올바른 유튜브 링크가 아닙니다.'}, status=400)

    stock = get_object_or_404(Info, code=stock_code)

    # 이미 저장된 영상이면 기존 id 반환 (저장 모달 등에서 바로 이동 가능)
    existing = YoutubeVideo.objects.filter(stock=stock, video_id=video_id).first()
    if existing:
        return JsonResponse({'success': True, 'id': existing.id, 'duplicate': True})

    # 유튜브 페이지에서 영상 정보 가져오기
    try:
        url = f'https://www.youtube.com/watch?v={video_id}'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'ko-KR,ko;q=0.9',
        }
        response = http_requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        # ytInitialPlayerResponse에서 정보 추출
        title = ''
        channel = ''
        thumbnail = ''
        views = ''
        published = ''

        # 유니코드 이스케이프 디코딩 함수
        def decode_unicode(s):
            try:
                return json.loads(f'"{s}"')
            except:
                return s

        # 제목 추출
        title_match = re.search(r'"title":"([^"]+)"', response.text)
        if title_match:
            title = decode_unicode(title_match.group(1))

        # 채널명 추출
        channel_match = re.search(r'"ownerChannelName":"([^"]+)"', response.text)
        if channel_match:
            channel = decode_unicode(channel_match.group(1))

        # 썸네일
        thumbnail = f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg'

        # 조회수 추출
        views_match = re.search(r'"viewCount":"(\d+)"', response.text)
        if views_match:
            view_count = int(views_match.group(1))
            if view_count >= 10000:
                views = f'조회수 {view_count // 10000}만회'
            elif view_count >= 1000:
                views = f'조회수 {view_count // 1000}천회'
            else:
                views = f'조회수 {view_count}회'

        # 업로드 날짜 추출 (여러 패턴 시도)
        date_match = re.search(r'"publishDate":"(\d{4}-\d{2}-\d{2})"', response.text)
        if date_match:
            published = date_match.group(1)
        else:
            # 대체 패턴 1: uploadDate
            date_match = re.search(r'"uploadDate":"(\d{4}-\d{2}-\d{2})"', response.text)
            if date_match:
                published = date_match.group(1)
            else:
                # 대체 패턴 2: dateText (절대 날짜)
                date_match = re.search(r'"dateText":\{"simpleText":"([^"]+)"\}', response.text)
                if date_match:
                    published = date_match.group(1)
                else:
                    # 대체 패턴 3: publishedTimeText (상대 시간 "1일 전" 등)
                    date_match = re.search(r'"publishedTimeText":\{"simpleText":"([^"]+)"\}', response.text)
                    if date_match:
                        published = date_match.group(1)

        if not title:
            return JsonResponse({'error': '영상 정보를 가져올 수 없습니다.'}, status=400)

        summary = request.POST.get('summary', '').strip()

        video = YoutubeVideo.objects.create(
            stock=stock,
            video_id=video_id,
            title=title,
            channel=channel,
            thumbnail=thumbnail,
            views=views,
            published=published,
            summary=summary,
        )

        return JsonResponse({
            'success': True,
            'id': video.id,
            'video_id': video.video_id,
            'title': video.title,
            'channel': video.channel,
            'thumbnail': video.thumbnail,
            'views': video.views,
            'published': video.published,
        })

    except Exception as e:
        return JsonResponse({'error': f'영상 정보를 가져오는 중 오류: {str(e)}'}, status=500)


@require_GET
def youtube_video_list(request, code):
    """종목 유튜브 목록 API (페이지네이션)"""
    from .models import YoutubeVideo
    stock = get_object_or_404(Info, code=code)
    limit = int(request.GET.get('limit', 30))
    offset = int(request.GET.get('offset', 0))
    qs = YoutubeVideo.objects.filter(stock=stock)
    total = qs.count()
    videos = qs[offset:offset + limit]
    results = []
    for v in videos:
        results.append({
            'id': v.id,
            'video_id': v.video_id,
            'title': v.title,
            'channel': v.channel,
            'note': v.my_opinion,
            'summary': v.summary,
            'url': v.link,
            'date': v.created_at.strftime('%Y-%m-%d'),
        })
    return JsonResponse({'success': True, 'results': results, 'total': total, 'has_more': offset + limit < total})


@require_POST
def youtube_video_update(request, video_id):
    """유튜브 영상 수정 API"""
    from .models import YoutubeVideo
    video = get_object_or_404(YoutubeVideo, id=video_id)
    note = request.POST.get('note')
    if note is not None:
        video.my_opinion = note.strip()
    summary = request.POST.get('summary')
    if summary is not None:
        video.summary = summary.strip()
    video.save()
    return JsonResponse({'success': True})


def _compute_technical_indicators(stock):
    """
    기술적 분석 프롬프트용 변수 계산 (DailyChart 기반).
    pandas로 SMA/RSI/MACD/Stochastic/ATR/Bollinger/OBV 등 산출.
    """
    import pandas as pd
    from datetime import date as _date, timedelta as _timedelta

    qs = list(DailyChart.objects.filter(
        stock=stock, date__gte=_date.today() - _timedelta(days=730)
    ).order_by('date').values('date', 'opening_price', 'high_price', 'low_price', 'closing_price', 'trading_volume'))

    if len(qs) < 5:
        return {}

    df = pd.DataFrame(qs).rename(columns={
        'opening_price': 'open', 'high_price': 'high',
        'low_price': 'low', 'closing_price': 'close',
        'trading_volume': 'volume',
    })
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # SMA
    for n in [5, 20, 60, 120, 200]:
        df[f'MA{n}'] = df['close'].rolling(n).mean()

    # RSI(14)
    delta = df['close'].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, float('nan'))
    df['RSI'] = 100 - (100 / (1 + rs))

    # MACD(12,26,9)
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_hist'] = df['MACD'] - df['MACD_signal']

    # Stochastic(14,3,3)
    low14 = df['low'].rolling(14).min()
    high14 = df['high'].rolling(14).max()
    range14 = (high14 - low14).replace(0, float('nan'))
    fast_k = 100 * (df['close'] - low14) / range14
    df['STO_K'] = fast_k.rolling(3).mean()
    df['STO_D'] = df['STO_K'].rolling(3).mean()

    # ATR(14)
    tr1 = df['high'] - df['low']
    tr2 = (df['high'] - df['close'].shift()).abs()
    tr3 = (df['low'] - df['close'].shift()).abs()
    df['ATR'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean()

    # Bollinger(20,2)
    bb_mid = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    df['BB_UP'] = bb_mid + 2 * bb_std
    df['BB_MID'] = bb_mid
    df['BB_LOW'] = bb_mid - 2 * bb_std

    # OBV
    sign = (df['close'].diff() > 0).astype(int) - (df['close'].diff() < 0).astype(int)
    df['OBV'] = (sign * df['volume']).cumsum()

    df['VOL_MA5'] = df['volume'].rolling(5).mean()
    df['VOL_MA20'] = df['volume'].rolling(20).mean()

    latest = df.iloc[-1]
    close = float(latest['close'])

    # 52주 고저
    win = df.tail(252)
    high52 = float(win['high'].max())
    low52 = float(win['low'].min())
    high52_date = win.loc[win['high'].idxmax(), 'date'].strftime('%Y-%m-%d')
    low52_date = win.loc[win['low'].idxmin(), 'date'].strftime('%Y-%m-%d')
    pos52 = (close - low52) / (high52 - low52) * 100 if high52 != low52 else 50.0

    # 이평 배열
    mas = [latest.get(f'MA{n}') for n in [5, 20, 60, 120, 200]]
    if all(pd.notna(v) for v in mas):
        if all(mas[i] >= mas[i+1] for i in range(4)):
            arrangement = "정배열(5>20>60>120>200)"
        elif all(mas[i] <= mas[i+1] for i in range(4)):
            arrangement = "역배열(5<20<60<120<200)"
        else:
            arrangement = "혼조 (단기/장기 다른 방향)"
    else:
        arrangement = "데이터 부족"

    # MACD 시그널 텍스트 (최근 10일 부호 변화)
    macd_sig_text = "최근 10거래일 내 시그널 변화 없음"
    if len(df) >= 10 and pd.notna(latest['MACD_hist']):
        recent10 = df['MACD_hist'].tail(10).values
        signs = [1 if v > 0 else -1 if v < 0 else 0 for v in recent10]
        for i in range(len(signs) - 1, 0, -1):
            if signs[i] and signs[i-1] and signs[i] != signs[i-1]:
                days_ago = len(signs) - 1 - i
                label = "골든크로스" if signs[i] > 0 else "데드크로스"
                macd_sig_text = f"오늘 {label}" if days_ago == 0 else f"{days_ago}거래일 전 {label}"
                break

    # OBV 추세
    obv_trend = "데이터 부족"
    if len(df) >= 20 and pd.notna(latest['OBV']):
        recent5 = float(df['OBV'].tail(5).mean())
        prev15 = float(df['OBV'].tail(20).head(15).mean())
        if prev15 == 0:
            obv_trend = "판단 불가"
        elif recent5 > prev15 * 1.02:
            obv_trend = "상승 추세"
        elif recent5 < prev15 * 0.98:
            obv_trend = "하락 추세"
        else:
            obv_trend = "횡보"

    # BB 위치
    bb_pos_text = ""
    if pd.notna(latest['BB_UP']) and pd.notna(latest['BB_LOW']) and pd.notna(latest['BB_MID']):
        if close >= latest['BB_UP']:
            bb_pos_text = "상단 돌파"
        elif close <= latest['BB_LOW']:
            bb_pos_text = "하단 돌파"
        else:
            denom = latest['BB_UP'] - latest['BB_MID']
            ratio = (close - latest['BB_MID']) / denom if denom else 0
            if ratio > 0.6:
                bb_pos_text = "상단 근접"
            elif ratio < -0.6:
                bb_pos_text = "하단 근접"
            else:
                bb_pos_text = "중심선 부근"

    bb_width = (latest['BB_UP'] - latest['BB_LOW']) / latest['BB_MID'] * 100 \
        if pd.notna(latest['BB_MID']) and latest['BB_MID'] != 0 else None

    high20 = float(df['high'].tail(20).max())
    low20 = float(df['low'].tail(20).min())
    high60 = float(df['high'].tail(60).max())
    low60 = float(df['low'].tail(60).min())

    vol_ratio = latest['volume'] / latest['VOL_MA20'] \
        if pd.notna(latest['VOL_MA20']) and latest['VOL_MA20'] > 0 else None

    # 주요 지지/저항 텍스트
    levels = []
    if pd.notna(latest['MA20']) and latest['MA20'] < close:
        levels.append(f"지지 20일선 {int(latest['MA20']):,}원")
    if pd.notna(latest['MA60']) and latest['MA60'] < close:
        levels.append(f"지지 60일선 {int(latest['MA60']):,}원")
    if high52 > close:
        levels.append(f"저항 52주고가 {int(high52):,}원")
    if pd.notna(latest['MA20']) and latest['MA20'] > close:
        levels.append(f"저항 20일선 {int(latest['MA20']):,}원")
    main_levels = ' / '.join(levels) if levels else '주요 레벨 없음'

    # 최근 5일 캔들
    candle_lines = []
    weekday_kr = ['월', '화', '수', '목', '금', '토', '일']
    for _, row in df.tail(5).iterrows():
        wd = weekday_kr[row['date'].weekday()]
        body = '양봉' if row['close'] > row['open'] else '음봉' if row['close'] < row['open'] else '도지'
        rng = row['high'] - row['low']
        body_size = abs(row['close'] - row['open'])
        cand = '장대' if rng > 0 and body_size > rng * 0.7 else '단봉' if rng > 0 and body_size < rng * 0.3 else ''
        v = row['volume']
        vstr = f"{v/1_000_000:.1f}M" if v >= 1_000_000 else f"{v/1_000:.0f}K" if v >= 1_000 else f"{int(v)}"
        candle_lines.append(
            f"{row['date'].strftime('%Y-%m-%d')} ({wd}) | 시 {int(row['open']):,} / 고 {int(row['high']):,} / 저 {int(row['low']):,} / 종 {int(row['close']):,} / 거래량 {vstr} | {body} {cand}".strip()
        )
    last5_text = '\n'.join(candle_lines)

    def fmt(v, dec=2):
        import pandas as _pd
        if v is None or _pd.isna(v):
            return ''
        try:
            if dec == 0:
                return f"{int(v):,}"
            return f"{float(v):.{dec}f}"
        except (TypeError, ValueError):
            return str(v)

    def gap(ma_val):
        if ma_val is None or pd.isna(ma_val) or ma_val == 0:
            return ''
        return fmt((close / ma_val - 1) * 100, 2)

    return {
        'high_52w_date': high52_date,
        'low_52w_date': low52_date,
        'pos_52w': fmt(pos52, 1),
        'MA5': fmt(latest.get('MA5'), 0),
        'MA20': fmt(latest.get('MA20'), 0),
        'MA60': fmt(latest.get('MA60'), 0),
        'MA120': fmt(latest.get('MA120'), 0),
        'MA200': fmt(latest.get('MA200'), 0),
        'gap_5': gap(latest.get('MA5')),
        'gap_20': gap(latest.get('MA20')),
        'gap_60': gap(latest.get('MA60')),
        'gap_120': gap(latest.get('MA120')),
        'gap_200': gap(latest.get('MA200')),
        'ma_arrangement': arrangement,
        'rsi': fmt(latest.get('RSI'), 1),
        'macd': fmt(latest.get('MACD'), 2),
        'macd_signal': fmt(latest.get('MACD_signal'), 2),
        'macd_hist': fmt(latest.get('MACD_hist'), 2),
        'macd_signal_text': macd_sig_text,
        'sto_k': fmt(latest.get('STO_K'), 1),
        'sto_d': fmt(latest.get('STO_D'), 1),
        'atr': fmt(latest.get('ATR'), 0),
        'atr_ratio': fmt(latest['ATR'] / close * 100 if pd.notna(latest.get('ATR')) and close > 0 else None, 2),
        'bb_up': fmt(latest.get('BB_UP'), 0),
        'bb_mid': fmt(latest.get('BB_MID'), 0),
        'bb_low': fmt(latest.get('BB_LOW'), 0),
        'bb_pos': bb_pos_text,
        'bb_width': fmt(bb_width, 2),
        'recent_volume': fmt(latest.get('volume'), 0),
        'vol_ma5': fmt(latest.get('VOL_MA5'), 0),
        'vol_ma20': fmt(latest.get('VOL_MA20'), 0),
        'vol_ratio': fmt(vol_ratio, 2),
        'obv_trend': obv_trend,
        'high_20': fmt(high20, 0),
        'low_20': fmt(low20, 0),
        'high_60': fmt(high60, 0),
        'low_60': fmt(low60, 0),
        'main_levels': main_levels,
        'recent5_candles': last5_text,
    }


def stock_question_report_detail(request, report_id):
    """리서치 상세/편집 페이지"""
    from .models import StockQuestionReport, ResearchPrompt, QuickReport, SystemSetting
    qr = get_object_or_404(StockQuestionReport, id=report_id)

    if request.method == 'POST':
        qr.question = request.POST.get('question', '').strip()
        qr.report = request.POST.get('report', '')
        qr.my_opinion = request.POST.get('my_opinion', '')
        qr.ai_question = request.POST.get('ai_question', '')
        qr.is_tracking = request.POST.get('is_tracking') == 'on'
        report_type = request.POST.get('report_type', 'html')
        if report_type in ('html', 'markdown'):
            qr.report_type = report_type
        qr.save()
        return redirect('stocks:stock_question_report_detail', report_id=report_id)

    research_prompts = ResearchPrompt.objects.all()
    quick_prompts = QuickReport.objects.all()
    from .models import SummaryReport, WaitingReport
    summary_prompts = SummaryReport.objects.all()
    waiting_prompts = WaitingReport.objects.all()
    # 업데이트 프롬프트 버튼 core/extra 분리
    _update_extra_qs = {'트래커', '매매대응'}
    _update_core_order = ['실적확인', '단기이슈', '중기이슈', '이벤트', '업황', '밸류확인']
    _update_extra_order = ['트래커', '매매대응']
    update_core_prompts = sorted([p for p in quick_prompts if p.question not in _update_extra_qs], key=lambda p: _update_core_order.index(p.question) if p.question in _update_core_order else 99)
    update_extra_prompts = sorted([p for p in quick_prompts if p.question in _update_extra_qs], key=lambda p: _update_extra_order.index(p.question) if p.question in _update_extra_order else 99)
    # 기업분석 core/extra 분리
    _core_questions = {'사업모델', '수익구조', '중장기전망', '지배구조', '경쟁력', '경쟁사'}
    _core_order = ['사업모델', '수익구조', '경쟁력', '경쟁사', '중장기전망', '지배구조']
    research_core = sorted([p for p in research_prompts if p.question in _core_questions], key=lambda p: _core_order.index(p.question) if p.question in _core_order else 99)
    research_extra = [p for p in research_prompts if p.question not in _core_questions]

    # 기업분석용 노다지 요약 (6개월 이내, 요약 있는 것만)
    nodaji_summaries = ''
    theme_category_name = ''
    theme_name = ''
    if qr.stock:
        from .models import Nodaji
        from datetime import date, timedelta
        six_months_ago = date.today() - timedelta(days=180)
        nodaji_list = Nodaji.objects.filter(
            stock=qr.stock,
            title__contains=qr.stock.name,
            date__gte=six_months_ago,
            summary__gt='',
        ).order_by('-date')
        parts = []
        for n in nodaji_list:
            parts.append(f"[{n.date.strftime('%Y-%m-%d') if n.date else '-'}] {n.title}\n{n.summary}")
        nodaji_summaries = '\n\n---\n\n'.join(parts)

        # 대분류/소분류
        first_theme = qr.stock.themes.select_related('category').first()
        if first_theme:
            theme_category_name = first_theme.category.name
            theme_name = first_theme.name

    # 밸류에이션용 데이터
    stock_current_price = ''
    consensus_eps = ''
    consensus_op = ''
    consensus_quarter_op = ''
    recent_q_revenue = ''
    recent_q_op = ''
    if qr.stock:
        from .models import Consensus, Financial
        from datetime import date
        today = date.today()
        current_year = today.year

        if qr.stock.current_price:
            stock_current_price = str(qr.stock.current_price)

        # 올해 연간 컨센서스
        annual = Consensus.objects.filter(
            stock=qr.stock, year=current_year, quarter__isnull=True
        ).first()
        if annual:
            if annual.eps is not None:
                consensus_eps = str(annual.eps)
            if annual.operating_profit is not None:
                consensus_op = str(int(annual.operating_profit))

        # 다음 분기 컨센서스 (현재 분기 또는 그 다음)
        current_q = (today.month - 1) // 3 + 1
        quarter_cons = Consensus.objects.filter(
            stock=qr.stock, year=current_year,
            quarter__isnull=False, quarter__gte=str(current_q)
        ).order_by('quarter').first()
        if not quarter_cons and current_q < 4:
            quarter_cons = Consensus.objects.filter(
                stock=qr.stock, year=current_year,
                quarter__isnull=False, quarter__gt=str(current_q)
            ).order_by('quarter').first()
        if quarter_cons and quarter_cons.operating_profit is not None:
            consensus_quarter_op = str(int(quarter_cons.operating_profit))

        # 최근 5개 분기 실적 (실적 분기 그래프와 동일 소스: Financial, 추정 포함 / 억원 단위)
        recent_q_fins = list(Financial.objects.filter(
            stock=qr.stock, quarter__isnull=False
        ).order_by('-year', '-quarter')[:5])
        _rev_lines = []
        _op_lines = []
        for f in recent_q_fins:
            label = f"{f.year} {f.quarter}" + ('(E)' if f.is_estimated else '')
            if f.revenue is not None:
                if f.is_estimated and f.revenue == 0:
                    _rev_lines.append(f"{label}: 없음")
                else:
                    _rev_lines.append(f"{label}: {int(f.revenue / 100000000):,}억원")
            if f.operating_profit is not None:
                if f.is_estimated and f.operating_profit == 0:
                    _op_lines.append(f"{label}: 없음")
                else:
                    _op_lines.append(f"{label}: {int(f.operating_profit / 100000000):,}억원")
        recent_q_revenue = '\n'.join(_rev_lines)
        recent_q_op = '\n'.join(_op_lines)

    # === 매매근거(Quick) 프롬프트용 변수 ===
    trade_prompt_vars = {}
    if qr.stock:
        from datetime import date as _date, timedelta as _timedelta
        from django.db.models import Max as _Max, Min as _Min
        from .models import InvestorTrend, ShortSelling

        def _fmt_num(v):
            if v is None or v == '':
                return ''
            try:
                return f"{int(v):,}"
            except (TypeError, ValueError):
                return str(v)

        # 52주 고저
        _today_d = _date.today()
        _yearly = DailyChart.objects.filter(
            stock=qr.stock, date__gte=_today_d - _timedelta(days=365)
        ).aggregate(high52=_Max('high_price'), low52=_Min('low_price'))
        _high52 = _yearly.get('high52')
        _low52 = _yearly.get('low52')

        # 최근 20거래일 수급
        _trends = list(InvestorTrend.objects.filter(stock=qr.stock).order_by('-date')[:20])
        if _trends:
            _supply_lines = ["날짜        | 외국인(주)   | 기관(주)     | 개인(주)"]
            for t in _trends:
                _supply_lines.append(
                    f"{t.date.strftime('%Y-%m-%d')}  | {int(t.foreign or 0):>12,} | {int(t.institution or 0):>12,} | {int(t.individual or 0):>12,}"
                )
            _supply_text = '\n'.join(_supply_lines)
        else:
            _supply_text = ''

        # 최근 20거래일 공매도
        _shorts = list(ShortSelling.objects.filter(stock=qr.stock).order_by('-date')[:20])
        if _shorts:
            _short_lines = ["날짜        | 공매도량(주) | 매매비중(%)  | 평균가(원)"]
            for s in _shorts:
                _short_lines.append(
                    f"{s.date.strftime('%Y-%m-%d')}  | {int(s.short_volume or 0):>12,} | {float(s.trading_weight or 0):>11.2f} | {int(s.short_average_price or 0):>10,}"
                )
            _short_text = '\n'.join(_short_lines)
        else:
            _short_text = ''

        # 향후 이벤트
        from .models import Schedule
        from django.db.models import Q as _Q
        _upcoming = Schedule.objects.filter(stock=qr.stock).filter(
            _Q(date_sort__gte=_today_d) | _Q(date_sort__isnull=True)
        ).order_by('date_sort')
        _events_text = '\n'.join(f"- {s.date_text}: {s.content}" for s in _upcoming)

        # 기술적 지표
        tech = _compute_technical_indicators(qr.stock)

        # 기업분석 결과 (질문명으로 매칭)
        _qr_reports = StockQuestionReport.objects.filter(stock=qr.stock)
        _qr_map = {r.question: r.report or '' for r in _qr_reports}

        # 컨센서스 텍스트 표 (밸류확인 프롬프트용 {연간컨센}/{분기컨센})
        from .models import Consensus as _Consensus
        _cfields = [('revenue', '매출'), ('operating_profit', '영익'), ('eps', 'EPS'),
                    ('per', 'PER'), ('pbr', 'PBR'), ('roe', 'ROE'), ('ev_ebitda', 'EV/EBITDA')]
        def _fmt_c(field, v):
            if v is None:
                return 'N/A'
            v = float(v)
            if field in ('revenue', 'operating_profit'):
                return f"{v:,.1f}"
            if field == 'eps':
                return f"{int(v):,}"
            return f"{v:,.2f}"
        def _consensus_text(rows):
            if not rows:
                return ''
            lines = ['기간\t' + '\t'.join(lbl for _, lbl in _cfields)]
            for o in rows:
                period = (str(o.year) if not o.quarter else f"{o.year} {o.quarter}") + ('(E)' if o.is_estimated else '(A)')
                lines.append('\t'.join([period] + [_fmt_c(f, getattr(o, f)) for f, _ in _cfields]))
            return '\n'.join(lines)
        _consensus_annual_text = _consensus_text(list(_Consensus.objects.filter(stock=qr.stock, quarter__isnull=True).order_by('year')))
        _consensus_quarter_text = _consensus_text(list(_Consensus.objects.filter(stock=qr.stock, quarter__isnull=False).order_by('year', 'quarter')))

        trade_prompt_vars = {
            'stock_name': qr.stock.name,
            'stock_code': qr.stock.code,
            'today': _today_d.strftime('%Y-%m-%d'),
            'market': qr.stock.market or '',
            'current_price': _fmt_num(qr.stock.current_price),
            'change_rate': f"{qr.stock.change_rate:+g}" if qr.stock.change_rate is not None else '',
            'market_cap': _fmt_num(qr.stock.market_cap),
            'per': str(qr.stock.per) if qr.stock.per is not None else '',
            'pbr': str(qr.stock.pbr) if qr.stock.pbr is not None else '',
            'high_52w': _fmt_num(_high52),
            'low_52w': _fmt_num(_low52),
            'avg_buy_price': _fmt_num(qr.stock.avg_buy_price),
            'supply_20d': _supply_text,
            'short_20d': _short_text,
            'consensus_annual_text': _consensus_annual_text,
            'consensus_quarter_text': _consensus_quarter_text,
            'key_briefing': qr.stock.key_briefing or '',
            'buy_reason': qr.stock.buy_reason or '',
            'sell_reason': qr.stock.sell_reason or '',
            'future_events': _events_text,
            **tech,
            **{f'기업분석: {q}': r for q, r in _qr_map.items()},
        }

    prompt_summary = SystemSetting.objects.filter(key='prompt_summary').values_list('value', flat=True).first() or ''

    # 전체내용복사용 데이터
    all_content_data = {}
    if qr.stock:
        _all_reports = StockQuestionReport.objects.filter(stock=qr.stock).exclude(id=qr.id)
        _common_set = set(research_prompts.values_list('question', flat=True))
        _quick_set = set(quick_prompts.values_list('question', flat=True)) | set(summary_prompts.values_list('question', flat=True))
        _common_reports = []
        _quick_reports = []
        for r in _all_reports:
            if r.question in _common_set and r.report:
                _common_reports.append({'question': r.question, 'report': r.report, 'updated_at': r.updated_at.strftime('%Y-%m-%d')})
            elif r.question in _quick_set and r.report:
                _quick_reports.append({'question': r.question, 'report': r.report, 'updated_at': r.updated_at.strftime('%Y-%m-%d')})
        all_content_data = {
            'common_reports': _common_reports,
            'quick_reports': _quick_reports,
            'key_briefing': qr.stock.key_briefing or '',
            'financial_analysis': qr.stock.financial_analysis_v2 or '',
            'consensus_analysis': qr.stock.consensus_analysis or '',
            'nodaji_summaries': nodaji_summaries,
        }

    return render(request, 'stocks/question_report_detail.html', {
        'qr': qr,
        'research_core': research_core,
        'research_extra': research_extra,
        'update_core_prompts': update_core_prompts,
        'update_extra_prompts': update_extra_prompts,
        'waiting_prompts': waiting_prompts,
        'nodaji_summaries': nodaji_summaries,
        'theme_category_name': theme_category_name,
        'theme_name': theme_name,
        'stock_current_price': stock_current_price,
        'consensus_eps': consensus_eps,
        'consensus_op': consensus_op,
        'consensus_quarter_op': consensus_quarter_op,
        'recent_q_revenue': recent_q_revenue,
        'recent_q_op': recent_q_op,
        'trade_prompt_vars': trade_prompt_vars,
        'prompt_summary': prompt_summary,
        'all_content_data': all_content_data,
        'recent_perf_report': StockQuestionReport.objects.filter(stock=qr.stock, question='실적확인').first().report if qr.stock and StockQuestionReport.objects.filter(stock=qr.stock, question='실적확인').exists() else '',
        'prev_tracker_report': StockQuestionReport.objects.filter(stock=qr.stock, question='트래커').first().report if qr.stock and StockQuestionReport.objects.filter(stock=qr.stock, question='트래커').exists() else '',
    })


def sector_question_report_detail(request, report_id):
    """섹터 리서치 상세/편집 페이지"""
    from .models import SectorQuestionReport, SystemSetting
    qr = get_object_or_404(SectorQuestionReport, id=report_id)

    if request.method == 'POST':
        qr.question = request.POST.get('question', '').strip()
        qr.report = request.POST.get('report', '')
        qr.my_opinion = request.POST.get('my_opinion', '')
        qr.ai_question = request.POST.get('ai_question', '')
        qr.is_tracking = request.POST.get('is_tracking') == 'on'
        report_type = request.POST.get('report_type', 'html')
        if report_type in ('html', 'markdown'):
            qr.report_type = report_type
        qr.save()
        return redirect('stocks:sector_question_report_detail', report_id=report_id)

    prompt_summary = SystemSetting.objects.filter(key='prompt_summary').values_list('value', flat=True).first() or ''

    return render(request, 'stocks/question_report_detail.html', {
        'qr': qr,
        'is_sector': True,
        'prompt_summary': prompt_summary,
    })


def _get_latest_quarter(stock):
    """종목의 최신 분기 데이터 감지 (포괄손익계산서 분기 기준)"""
    from .models import IncomeStatement
    latest = IncomeStatement.objects.filter(
        stock=stock, quarter__isnull=False
    ).order_by('-year', '-quarter').first()
    if latest:
        return f"{latest.year}/{latest.quarter}"
    return ''


@require_POST
def financial_analysis_v2_save(request, code):
    """기업분석 탭 재무분석 저장 (현재→과거 자동 보관)"""
    from datetime import date
    stock = get_object_or_404(Info, code=code)
    text = request.POST.get('content', '').strip()
    base_quarter = _get_latest_quarter(stock)
    # 현재값이 있으면 과거로 밀기
    if stock.financial_analysis_v2:
        stock.financial_analysis_v2_previous = stock.financial_analysis_v2
        stock.financial_analysis_v2_previous_updated_at = stock.financial_analysis_v2_updated_at
        stock.financial_analysis_v2_previous_base_quarter = stock.financial_analysis_v2_base_quarter
    stock.financial_analysis_v2 = text
    stock.financial_analysis_v2_updated_at = date.today()
    stock.financial_analysis_v2_base_quarter = base_quarter
    opinion = request.POST.get('my_opinion')
    if opinion is not None:
        stock.financial_analysis_v2_opinion = opinion
    stock.save(update_fields=[
        'financial_analysis_v2', 'financial_analysis_v2_previous',
        'financial_analysis_v2_previous_updated_at', 'financial_analysis_v2_previous_base_quarter',
        'financial_analysis_v2_updated_at', 'financial_analysis_v2_base_quarter',
        'financial_analysis_v2_opinion',
    ])
    return JsonResponse({'success': True, 'updated_at': stock.financial_analysis_v2_updated_at.strftime('%Y-%m-%d'), 'base_quarter': base_quarter})


@require_POST
def consensus_analysis_save(request, code):
    """컨센서스분석 저장 (현재→과거 자동 보관)"""
    from datetime import date
    stock = get_object_or_404(Info, code=code)
    text = request.POST.get('content', '').strip()
    base_quarter = _get_latest_quarter(stock)
    # 현재값이 있으면 과거로 밀기
    if stock.consensus_analysis:
        stock.consensus_analysis_previous = stock.consensus_analysis
        stock.consensus_analysis_previous_updated_at = stock.consensus_analysis_updated_at
        stock.consensus_analysis_previous_base_quarter = stock.consensus_analysis_base_quarter
    stock.consensus_analysis = text
    stock.consensus_analysis_updated_at = date.today()
    stock.consensus_analysis_base_quarter = base_quarter
    opinion = request.POST.get('my_opinion')
    if opinion is not None:
        stock.consensus_analysis_opinion = opinion
    stock.save(update_fields=[
        'consensus_analysis', 'consensus_analysis_previous',
        'consensus_analysis_previous_updated_at', 'consensus_analysis_previous_base_quarter',
        'consensus_analysis_updated_at', 'consensus_analysis_base_quarter',
        'consensus_analysis_opinion',
    ])
    return JsonResponse({'success': True, 'updated_at': stock.consensus_analysis_updated_at.strftime('%Y-%m-%d'), 'base_quarter': base_quarter})






def _parse_financial_table(raw_text, field_map, first_labels=None, int_fields=None, debug=False):
    """
    FnGuide 재무 테이블 붙여넣기 텍스트 범용 파서

    - field_map: {'항목명': 'field_name', ...}
    - first_labels: 데이터 시작 감지용 라벨 목록 (기본: field_map 키 사용)
    - int_fields: 정수로 변환할 필드명 집합
    """
    import re
    from decimal import Decimal, InvalidOperation

    debug_info = {}
    if int_fields is None:
        int_fields = set()
    raw_text = raw_text.replace('\r\n', '\n').replace('\r', '\n')
    # 비표준 공백(NBSP, 한자공백, 좁은공백 등) → 일반 공백
    for ch in (' ', '　', ' ', ' ', '​', '﻿'):
        raw_text = raw_text.replace(ch, ' ')

    # 공백 기반 paste 지원: FnGuide에서 탭이 보존되지 않고 공백으로 들어오는 경우 정규화.
    # 값 라인(선두에 공백 있음)과 헤더/라벨 라인(텍스트로 시작)을 구분해 다르게 처리.
    # - 값 라인: 선두 공백 → 행 라벨 슬롯 탭, 7+ 연속 공백 → 빈 셀 포함 \t\t,
    #   2-6 공백 → 일반 셀 구분자 \t
    # - 헤더/라벨 라인: 시각적 패딩(12+ 공백 등)을 빈 셀로 오해하지 않도록 2+ 공백 모두 단일 탭
    new_lines = []
    for ln in raw_text.split('\n'):
        if ln.startswith(' '):
            ln = re.sub(r'^ +', '\t', ln)
            ln = re.sub(r' {7,}', '\t\t', ln)
            ln = re.sub(r' {2,}', '\t', ln)
        else:
            ln = re.sub(r' {2,}', '\t', ln)
        new_lines.append(ln)
    raw_text = '\n'.join(new_lines)
    debug_info['normalized_first_10_lines'] = [repr(l) for l in raw_text.split('\n')[:10]]

    lines = raw_text.strip().split('\n')
    if not lines:
        return ([], debug_info) if debug else []

    debug_info['total_lines'] = len(lines)
    debug_info['first_5_lines'] = [repr(l) for l in lines[:5]]

    # Step 1: 데이터 시작 지점 찾기
    if first_labels is None:
        first_labels = list(field_map.keys())[:3]
    data_start = 0
    for i, line in enumerate(lines):
        clean = re.sub(r'^(펼치기\s*|\s+)', '', line.strip())
        if any(clean.startswith(label) for label in first_labels):
            data_start = i
            break

    debug_info['data_start'] = data_start
    if data_start == 0:
        debug_info['error'] = 'data_start=0, 항목 라벨을 찾지 못함'
        return ([], debug_info) if debug else []

    # Step 2: 헤더 줄들을 합쳐서 컬럼 복원
    header_text = ''.join(lines[:data_start])
    header_cols = header_text.split('\t')

    debug_info['header_col_count'] = len(header_cols)
    debug_info['header_cols'] = [repr(c[:50]) for c in header_cols]

    # Step 3: 각 컬럼이 기간인지 판별
    period_pattern = re.compile(r'(\d{4})/(\d{2})(\(E\))?')
    month_to_quarter = {3: '1Q', 6: '2Q', 9: '3Q', 12: '4Q'}

    columns = []
    for col in header_cols[1:]:
        m = period_pattern.search(col)
        if m:
            year = int(m.group(1))
            month = int(m.group(2))
            is_estimated = bool(m.group(3))
            quarter = month_to_quarter.get(month)
            columns.append({'year': year, 'month': month, 'quarter': quarter, 'is_estimated': is_estimated})
        else:
            columns.append(None)

    # 첫 번째 연속 기간 컬럼 그룹만 사용. 단, 선두에 빈/패딩 컬럼이 있을 수 있으므로
    # 유효한 기간을 처음 만난 이후의 None에서만 truncate.
    seen_period = False
    for i, col in enumerate(columns):
        if col is None:
            if seen_period:
                columns[i:] = [None] * (len(columns) - i)
                break
        else:
            seen_period = True

    debug_info['columns'] = [str(c) for c in columns if c is not None]

    if not any(c for c in columns):
        debug_info['error'] = '유효한 기간 컬럼 없음'
        return ([], debug_info) if debug else []

    # Step 4: 데이터 행 파싱
    def parse_number(s):
        s = s.strip().replace(',', '')
        if not s:
            return None
        try:
            return Decimal(s)
        except InvalidOperation:
            return None

    data_by_period = {}
    matched_labels = []
    i = data_start
    while i < len(lines):
        line = lines[i]
        label = re.sub(r'^(펼치기\s*)', '', line.strip()).strip()

        field_name = field_map.get(label)
        if field_name is not None and i + 1 < len(lines):
            values_line = lines[i + 1]
            values = values_line.split('\t')
            # 헤더는 [항목, P1, P2, ...] 형태이고 값 라인은 보통 [<empty>, V1, V2, ...]로
            # 첫 칸이 행 라벨 자리(빈 칸)이다. 헤더 정렬에 맞추려면 빈 첫 칸을 버린다.
            # 신규상장 등으로 일부 기간 값이 비어 있을 때 1칸 어긋나면 모든 값이 한 칸씩
            # 잘못 매핑돼 결과적으로 저장이 누락된다.
            if values and values[0].strip() == '':
                values = values[1:]
            matched_labels.append({'label': label, 'field': field_name, 'values_count': len(values)})

            for j, val_str in enumerate(values):
                if j >= len(columns) or columns[j] is None:
                    continue
                p = columns[j]
                key = (p['year'], p['quarter'])
                if key not in data_by_period:
                    data_by_period[key] = {'year': p['year'], 'month': p['month'], 'quarter': p['quarter'], 'is_estimated': p['is_estimated']}
                val = parse_number(val_str)
                if val is not None:
                    data_by_period[key][field_name] = int(val) if field_name in int_fields else val
            i += 2
        else:
            i += 1

    debug_info['matched_labels'] = matched_labels
    debug_info['result_periods'] = list(data_by_period.keys())

    result = list(data_by_period.values())
    return (result, debug_info) if debug else result


# 테이블별 필드 매핑
INCOME_STATEMENT_FIELDS = {
    '매출액(수익)': 'revenue',
    '매출액': 'revenue',
    '순영업이익': 'revenue',
    '매출원가': 'cost_of_revenue',
    '매출총이익': 'gross_profit',
    '판매비와관리비': 'sga_expense',
    '영업이익': 'operating_profit',
    '법인세비용차감전계속사업이익': 'pretax_income',
    '당기순이익': 'net_income',
    '*(지배주주지분)주당순이익': 'eps',
}

BALANCE_SHEET_FIELDS = {
    '자산총계': 'total_assets',
    '자산': 'total_assets',
    '현금및현금성자산': 'cash',
    '현금및예치금': 'cash',
    '매출채권및기타채권': 'receivables',
    '대출채권': 'receivables',
    '유형자산': 'tangible_assets',
    '부채총계': 'total_liabilities',
    '부채': 'total_liabilities',
    '단기차입금': 'short_term_debt',
    '장기차입금': 'long_term_debt',
    '차입부채': 'long_term_debt',
    '자본총계': 'total_equity',
    '자본': 'total_equity',
    '이익잉여금': 'retained_earnings',
    '*이자발생부채': 'interest_bearing_debt',
    '*순부채': 'net_debt',
    '*CAPEX': 'capex',
}

CONSENSUS_COL_MAP = {
    '매출액': ('revenue', 'decimal'),
    'YoY': ('yoy', 'decimal'),
    '영업이익': ('operating_profit', 'decimal'),
    '당기순이익': ('net_income', 'decimal'),
    'EPS': ('eps', 'int'),
    'BPS': ('bps', 'int'),
    'PER': ('per', 'decimal'),
    'PBR': ('pbr', 'decimal'),
    'ROE': ('roe', 'decimal'),
    'EV/EBITDA': ('ev_ebitda', 'decimal'),
}

GROWTH_FIELDS = {
    '매출액증가율': 'revenue_growth',
    '영업이익증가율': 'operating_profit_growth',
    '순이익증가율': 'net_income_growth',
    '자기자본증가율': 'equity_growth',
}

PROFITABILITY_FIELDS = {
    '영업이익률': 'operating_margin',
    '순이익률': 'net_margin',
    'EBITDA마진율': 'ebitda_margin',
    'ROE': 'roe',
    'ROIC': 'roic',
}

STABILITY_FIELDS = {
    '부채비율': 'debt_ratio',
    '순부채비율': 'net_debt_ratio',
    '유동비율': 'current_ratio',
    '이자보상배율': 'interest_coverage',
}

CASH_FLOW_FIELDS = {
    '영업활동으로인한현금흐름': 'operating_cash_flow',
    '당기순이익': 'net_income',
    '영업활동으로인한자산부채변동(운전자본변동)': 'working_capital_change',
    '영업활동으로인한자산부채변동': 'working_capital_change',
    '이자지급(-)': 'interest_paid',
    '법인세납부(-)': 'tax_paid',
    '투자활동으로인한현금흐름': 'investing_cash_flow',
    '재무활동으로인한현금흐름': 'financing_cash_flow',
    '배당금지급(-)': 'dividends_paid',
    '현금및현금성자산의증가': 'cash_change',
    '기말현금및현금성자산': 'ending_cash',
}


@require_POST
def income_statement_save(request, code):
    """포괄손익계산서 붙여넣기 파싱 후 저장"""
    from .models import IncomeStatement
    stock = get_object_or_404(Info, code=code)
    raw_text = request.POST.get('raw_text', '').strip()

    if not raw_text:
        return JsonResponse({'success': False, 'error': '데이터가 비어있습니다.'})

    parsed, debug = _parse_financial_table(raw_text, INCOME_STATEMENT_FIELDS,
                                             first_labels=['매출액', '매출원가', '*내수', '*수출',
                                                           '순이자이익', '순수수료이익', '순영업이익'],
                                             int_fields={'eps'}, debug=True)
    if not parsed:
        return JsonResponse({'success': False, 'error': '파싱된 데이터가 없습니다.', 'debug': debug})

    # 연간/분기 자동 감지: 모든 기간이 12월이면 연간, 아니면 분기
    months = set(row.get('month') for row in parsed if row.get('month'))
    is_annual = months == {12}

    saved_count = 0
    for row in parsed:
        if is_annual:
            row['quarter'] = None
        obj, created = IncomeStatement.objects.update_or_create(
            stock=stock,
            year=row['year'],
            quarter=row.get('quarter'),
            defaults={
                'is_estimated': row.get('is_estimated', False),
                'revenue': row.get('revenue'),
                'cost_of_revenue': row.get('cost_of_revenue'),
                'gross_profit': row.get('gross_profit'),
                'sga_expense': row.get('sga_expense'),
                'operating_profit': row.get('operating_profit'),
                'pretax_income': row.get('pretax_income'),
                'net_income': row.get('net_income'),
                'eps': row.get('eps'),
            }
        )
        saved_count += 1

    period_type = '연간' if is_annual else '분기'
    return JsonResponse({'success': True, 'saved_count': saved_count, 'period_type': period_type, 'debug': debug})


@require_GET
def income_statement_list(request, code):
    """포괄손익계산서 조회"""
    from .models import IncomeStatement
    stock = get_object_or_404(Info, code=code)
    period_type = request.GET.get('period_type', 'annual')

    if period_type == 'annual':
        qs = IncomeStatement.objects.filter(stock=stock, quarter__isnull=True).order_by('year')
    else:
        qs = IncomeStatement.objects.filter(stock=stock, quarter__isnull=False).order_by('year', 'quarter')

    data = []
    for obj in qs:
        period = f"{obj.year}" if not obj.quarter else f"{obj.year}/{obj.quarter}"
        data.append({
            'period': period,
            'year': obj.year,
            'quarter': obj.quarter,
            'is_estimated': obj.is_estimated,
            'revenue': str(obj.revenue) if obj.revenue is not None else None,
            'cost_of_revenue': str(obj.cost_of_revenue) if obj.cost_of_revenue is not None else None,
            'gross_profit': str(obj.gross_profit) if obj.gross_profit is not None else None,
            'sga_expense': str(obj.sga_expense) if obj.sga_expense is not None else None,
            'operating_profit': str(obj.operating_profit) if obj.operating_profit is not None else None,
            'pretax_income': str(obj.pretax_income) if obj.pretax_income is not None else None,
            'net_income': str(obj.net_income) if obj.net_income is not None else None,
            'eps': obj.eps,
        })

    return JsonResponse({'success': True, 'data': data})


@require_POST
def balance_sheet_save(request, code):
    """재무상태표 붙여넣기 파싱 후 저장"""
    from .models import BalanceSheet
    stock = get_object_or_404(Info, code=code)
    raw_text = request.POST.get('raw_text', '').strip()

    if not raw_text:
        return JsonResponse({'success': False, 'error': '데이터가 비어있습니다.'})

    parsed, debug = _parse_financial_table(raw_text, BALANCE_SHEET_FIELDS,
                                           first_labels=['자산총계', '유동자산', '비유동자산',
                                                         '자산', '현금및예치금'],
                                           debug=True)
    if not parsed:
        return JsonResponse({'success': False, 'error': '파싱된 데이터가 없습니다.', 'debug': debug})

    months = set(row.get('month') for row in parsed if row.get('month'))
    is_annual = months == {12}

    saved_count = 0
    for row in parsed:
        if is_annual:
            row['quarter'] = None
        BalanceSheet.objects.update_or_create(
            stock=stock,
            year=row['year'],
            quarter=row.get('quarter'),
            defaults={
                'is_estimated': row.get('is_estimated', False),
                'total_assets': row.get('total_assets'),
                'cash': row.get('cash'),
                'receivables': row.get('receivables'),
                'tangible_assets': row.get('tangible_assets'),
                'total_liabilities': row.get('total_liabilities'),
                'short_term_debt': row.get('short_term_debt'),
                'long_term_debt': row.get('long_term_debt'),
                'total_equity': row.get('total_equity'),
                'retained_earnings': row.get('retained_earnings'),
                'interest_bearing_debt': row.get('interest_bearing_debt'),
                'net_debt': row.get('net_debt'),
                'capex': row.get('capex'),
            }
        )
        saved_count += 1

    period_type = '연간' if is_annual else '분기'
    return JsonResponse({'success': True, 'saved_count': saved_count, 'period_type': period_type, 'debug': debug})


@require_GET
def balance_sheet_list(request, code):
    """재무상태표 조회"""
    from .models import BalanceSheet
    stock = get_object_or_404(Info, code=code)
    period_type = request.GET.get('period_type', 'annual')

    if period_type == 'annual':
        qs = BalanceSheet.objects.filter(stock=stock, quarter__isnull=True).order_by('year')
    else:
        qs = BalanceSheet.objects.filter(stock=stock, quarter__isnull=False).order_by('year', 'quarter')

    fields = ['total_assets', 'cash', 'receivables', 'tangible_assets', 'total_liabilities',
              'short_term_debt', 'long_term_debt', 'total_equity', 'retained_earnings',
              'interest_bearing_debt', 'net_debt', 'capex']
    data = []
    for obj in qs:
        period = f"{obj.year}" if not obj.quarter else f"{obj.year}/{obj.quarter}"
        row = {'period': period, 'year': obj.year, 'quarter': obj.quarter, 'is_estimated': obj.is_estimated}
        for f in fields:
            val = getattr(obj, f)
            row[f] = str(val) if val is not None else None
        data.append(row)

    return JsonResponse({'success': True, 'data': data})


def _parse_consensus(raw_text):
    """컨센서스 테이블 파싱 (행=연도, 열=항목 구조)"""
    import re
    from decimal import Decimal, InvalidOperation

    raw_text = raw_text.replace('\r\n', '\n').replace('\r', '\n')
    lines = raw_text.strip().split('\n')
    if not lines:
        return []

    # 헤더 찾기: '재무년월'로 시작하는 줄까지가 헤더
    header_end = 0
    for i, line in enumerate(lines):
        if re.search(r'\d{4}\.\d{2}\([AE]\)', line):
            header_end = i
            break

    # 헤더 복원
    header_text = ''.join(lines[:header_end])
    header_cols = header_text.split('\t')

    # 컬럼 매핑
    col_indices = {}
    for idx, col in enumerate(header_cols):
        # 줄바꿈 제거 후 키워드 매칭
        col_clean = re.sub(r'\(.*?\)', '', col).strip()
        for key, (field, _) in CONSENSUS_COL_MAP.items():
            if col_clean == key:
                col_indices[idx] = (field, CONSENSUS_COL_MAP[key][1])
                break

    def parse_num(s, num_type):
        s = s.strip().replace(',', '')
        if not s:
            return None
        try:
            if num_type == 'int':
                return int(Decimal(s))
            return Decimal(s)
        except (InvalidOperation, ValueError):
            return None

    # 데이터 행 파싱
    results = []
    for line in lines[header_end:]:
        cols = line.split('\t')
        if not cols:
            continue
        # 기간 파싱: 2022.12(A), 2026.12(E), 2025.03(A) 등
        m = re.match(r'(\d{4})\.(\d{2})\(([AE])\)', cols[0].strip())
        if not m:
            continue
        year = int(m.group(1))
        month = int(m.group(2))
        is_estimated = m.group(3) == 'E'
        month_to_quarter = {3: '1Q', 6: '2Q', 9: '3Q', 12: '4Q'}
        quarter = month_to_quarter.get(month)

        row = {'year': year, 'month': month, 'quarter': quarter, 'is_estimated': is_estimated}
        for idx, (field, num_type) in col_indices.items():
            if idx < len(cols):
                val = parse_num(cols[idx], num_type)
                if val is not None:
                    row[field] = val
        results.append(row)

    return results


@require_POST
def consensus_save(request, code):
    """컨센서스 붙여넣기 파싱 후 저장"""
    from .models import Consensus
    stock = get_object_or_404(Info, code=code)
    raw_text = request.POST.get('raw_text', '').strip()
    if not raw_text:
        return JsonResponse({'success': False, 'error': '데이터가 비어있습니다.'})

    parsed = _parse_consensus(raw_text)
    if not parsed:
        return JsonResponse({'success': False, 'error': '파싱된 데이터가 없습니다.'})

    months = set(row.get('month') for row in parsed if row.get('month'))
    is_annual = months == {12}

    c_fields = ['revenue', 'yoy', 'operating_profit', 'net_income', 'eps', 'bps', 'per', 'pbr', 'roe', 'ev_ebitda']
    saved_count = 0
    for row in parsed:
        if is_annual:
            row['quarter'] = None
        defaults = {'is_estimated': row.get('is_estimated', False)}
        for f in c_fields:
            defaults[f] = row.get(f)
        Consensus.objects.update_or_create(stock=stock, year=row['year'], quarter=row.get('quarter'), defaults=defaults)
        saved_count += 1

    period_type = '연간' if is_annual else '분기'
    return JsonResponse({'success': True, 'saved_count': saved_count, 'period_type': period_type})


@require_GET
def consensus_list(request, code):
    """컨센서스 조회"""
    from .models import Consensus
    stock = get_object_or_404(Info, code=code)
    period_type = request.GET.get('period_type', 'annual')

    if period_type == 'annual':
        qs = Consensus.objects.filter(stock=stock, quarter__isnull=True).order_by('year')
    else:
        qs = Consensus.objects.filter(stock=stock, quarter__isnull=False).order_by('year', 'quarter')

    c_fields = ['revenue', 'yoy', 'operating_profit', 'net_income', 'eps', 'bps', 'per', 'pbr', 'roe', 'ev_ebitda']
    data = []
    for obj in qs:
        period = f"{obj.year}" if not obj.quarter else f"{obj.year}/{obj.quarter}"
        row = {'period': period, 'year': obj.year, 'quarter': obj.quarter, 'is_estimated': obj.is_estimated}
        for f in c_fields:
            val = getattr(obj, f)
            if f in ('eps', 'bps'):
                row[f] = val
            else:
                row[f] = str(val) if val is not None else None
        data.append(row)

    return JsonResponse({'success': True, 'data': data})


@require_POST
def growth_save(request, code):
    """성장성 붙여넣기 파싱 후 저장"""
    from .models import GrowthRatio
    stock = get_object_or_404(Info, code=code)
    raw_text = request.POST.get('raw_text', '').strip()
    if not raw_text:
        return JsonResponse({'success': False, 'error': '데이터가 비어있습니다.'})
    parsed, debug = _parse_financial_table(raw_text, GROWTH_FIELDS, first_labels=['매출액증가율', '영업이익증가율'], debug=True)
    if not parsed:
        return JsonResponse({'success': False, 'error': '파싱된 데이터가 없습니다.', 'debug': debug})
    months = set(row.get('month') for row in parsed if row.get('month'))
    is_annual = months == {12}
    gr_fields = ['revenue_growth', 'operating_profit_growth', 'net_income_growth', 'equity_growth']
    saved_count = 0
    for row in parsed:
        if is_annual:
            row['quarter'] = None
        defaults = {'is_estimated': row.get('is_estimated', False)}
        for f in gr_fields:
            defaults[f] = row.get(f)
        GrowthRatio.objects.update_or_create(stock=stock, year=row['year'], quarter=row.get('quarter'), defaults=defaults)
        saved_count += 1
    return JsonResponse({'success': True, 'saved_count': saved_count, 'period_type': '연간' if is_annual else '분기'})


@require_GET
def growth_list(request, code):
    """성장성 조회"""
    from .models import GrowthRatio
    stock = get_object_or_404(Info, code=code)
    period_type = request.GET.get('period_type', 'annual')
    if period_type == 'annual':
        qs = GrowthRatio.objects.filter(stock=stock, quarter__isnull=True).order_by('year')
    else:
        qs = GrowthRatio.objects.filter(stock=stock, quarter__isnull=False).order_by('year', 'quarter')
    fields = ['revenue_growth', 'operating_profit_growth', 'net_income_growth', 'equity_growth']
    data = []
    for obj in qs:
        period = f"{obj.year}" if not obj.quarter else f"{obj.year}/{obj.quarter}"
        row = {'period': period, 'year': obj.year, 'quarter': obj.quarter, 'is_estimated': obj.is_estimated}
        for f in fields:
            val = getattr(obj, f)
            row[f] = str(val) if val is not None else None
        data.append(row)
    return JsonResponse({'success': True, 'data': data})


@require_POST
def profitability_save(request, code):
    """수익성 붙여넣기 파싱 후 저장"""
    from .models import ProfitabilityRatio
    stock = get_object_or_404(Info, code=code)
    raw_text = request.POST.get('raw_text', '').strip()
    if not raw_text:
        return JsonResponse({'success': False, 'error': '데이터가 비어있습니다.'})

    parsed, debug = _parse_financial_table(raw_text, PROFITABILITY_FIELDS,
                                           first_labels=['매출총이익률', '영업이익률'],
                                           debug=True)
    if not parsed:
        return JsonResponse({'success': False, 'error': '파싱된 데이터가 없습니다.', 'debug': debug})

    months = set(row.get('month') for row in parsed if row.get('month'))
    is_annual = months == {12}
    pf_fields = ['operating_margin', 'net_margin', 'ebitda_margin', 'roe', 'roic']
    saved_count = 0
    for row in parsed:
        if is_annual:
            row['quarter'] = None
        defaults = {'is_estimated': row.get('is_estimated', False)}
        for f in pf_fields:
            defaults[f] = row.get(f)
        ProfitabilityRatio.objects.update_or_create(
            stock=stock, year=row['year'], quarter=row.get('quarter'), defaults=defaults)
        saved_count += 1
    return JsonResponse({'success': True, 'saved_count': saved_count, 'period_type': '연간' if is_annual else '분기'})


@require_GET
def profitability_list(request, code):
    """수익성 조회"""
    from .models import ProfitabilityRatio
    stock = get_object_or_404(Info, code=code)
    period_type = request.GET.get('period_type', 'annual')
    if period_type == 'annual':
        qs = ProfitabilityRatio.objects.filter(stock=stock, quarter__isnull=True).order_by('year')
    else:
        qs = ProfitabilityRatio.objects.filter(stock=stock, quarter__isnull=False).order_by('year', 'quarter')
    fields = ['operating_margin', 'net_margin', 'ebitda_margin', 'roe', 'roic']
    data = []
    for obj in qs:
        period = f"{obj.year}" if not obj.quarter else f"{obj.year}/{obj.quarter}"
        row = {'period': period, 'year': obj.year, 'quarter': obj.quarter, 'is_estimated': obj.is_estimated}
        for f in fields:
            val = getattr(obj, f)
            row[f] = str(val) if val is not None else None
        data.append(row)
    return JsonResponse({'success': True, 'data': data})


@require_POST
def stability_save(request, code):
    """안정성 붙여넣기 파싱 후 저장"""
    from .models import StabilityRatio
    stock = get_object_or_404(Info, code=code)
    raw_text = request.POST.get('raw_text', '').strip()

    if not raw_text:
        return JsonResponse({'success': False, 'error': '데이터가 비어있습니다.'})

    parsed, debug = _parse_financial_table(raw_text, STABILITY_FIELDS,
                                           first_labels=['부채비율', '유동부채비율'],
                                           debug=True)
    if not parsed:
        return JsonResponse({'success': False, 'error': '파싱된 데이터가 없습니다.', 'debug': debug})

    months = set(row.get('month') for row in parsed if row.get('month'))
    is_annual = months == {12}

    pf_fields = ['debt_ratio', 'net_debt_ratio', 'current_ratio', 'interest_coverage']
    saved_count = 0
    for row in parsed:
        if is_annual:
            row['quarter'] = None
        defaults = {'is_estimated': row.get('is_estimated', False)}
        for f in pf_fields:
            defaults[f] = row.get(f)
        StabilityRatio.objects.update_or_create(
            stock=stock, year=row['year'], quarter=row.get('quarter'),
            defaults=defaults
        )
        saved_count += 1

    period_type = '연간' if is_annual else '분기'
    return JsonResponse({'success': True, 'saved_count': saved_count, 'period_type': period_type})


@require_GET
def stability_list(request, code):
    """안정성 조회"""
    from .models import StabilityRatio
    stock = get_object_or_404(Info, code=code)
    period_type = request.GET.get('period_type', 'annual')

    if period_type == 'annual':
        qs = StabilityRatio.objects.filter(stock=stock, quarter__isnull=True).order_by('year')
    else:
        qs = StabilityRatio.objects.filter(stock=stock, quarter__isnull=False).order_by('year', 'quarter')

    fields = ['debt_ratio', 'net_debt_ratio', 'current_ratio', 'interest_coverage']
    data = []
    for obj in qs:
        period = f"{obj.year}" if not obj.quarter else f"{obj.year}/{obj.quarter}"
        row = {'period': period, 'year': obj.year, 'quarter': obj.quarter, 'is_estimated': obj.is_estimated}
        for f in fields:
            val = getattr(obj, f)
            row[f] = str(val) if val is not None else None
        data.append(row)

    return JsonResponse({'success': True, 'data': data})


@require_POST
def cash_flow_save(request, code):
    """현금흐름표 붙여넣기 파싱 후 저장"""
    from .models import CashFlow
    stock = get_object_or_404(Info, code=code)
    raw_text = request.POST.get('raw_text', '').strip()

    if not raw_text:
        return JsonResponse({'success': False, 'error': '데이터가 비어있습니다.'})

    parsed, debug = _parse_financial_table(raw_text, CASH_FLOW_FIELDS,
                                           first_labels=['영업활동으로인한현금흐름', '당기순이익'],
                                           debug=True)
    if not parsed:
        return JsonResponse({'success': False, 'error': '파싱된 데이터가 없습니다.', 'debug': debug})

    months = set(row.get('month') for row in parsed if row.get('month'))
    is_annual = months == {12}

    cf_fields = ['operating_cash_flow', 'net_income', 'working_capital_change', 'interest_paid',
                 'tax_paid', 'investing_cash_flow', 'financing_cash_flow', 'dividends_paid',
                 'cash_change', 'ending_cash']
    saved_count = 0
    for row in parsed:
        if is_annual:
            row['quarter'] = None
        defaults = {'is_estimated': row.get('is_estimated', False)}
        for f in cf_fields:
            defaults[f] = row.get(f)
        CashFlow.objects.update_or_create(
            stock=stock, year=row['year'], quarter=row.get('quarter'),
            defaults=defaults
        )
        saved_count += 1

    period_type = '연간' if is_annual else '분기'
    return JsonResponse({'success': True, 'saved_count': saved_count, 'period_type': period_type})


@require_GET
def cash_flow_list(request, code):
    """현금흐름표 조회"""
    from .models import CashFlow
    stock = get_object_or_404(Info, code=code)
    period_type = request.GET.get('period_type', 'annual')

    if period_type == 'annual':
        qs = CashFlow.objects.filter(stock=stock, quarter__isnull=True).order_by('year')
    else:
        qs = CashFlow.objects.filter(stock=stock, quarter__isnull=False).order_by('year', 'quarter')

    fields = ['operating_cash_flow', 'net_income', 'working_capital_change', 'interest_paid',
              'tax_paid', 'investing_cash_flow', 'financing_cash_flow', 'dividends_paid',
              'cash_change', 'ending_cash']
    data = []
    for obj in qs:
        period = f"{obj.year}" if not obj.quarter else f"{obj.year}/{obj.quarter}"
        row = {'period': period, 'year': obj.year, 'quarter': obj.quarter, 'is_estimated': obj.is_estimated}
        for f in fields:
            val = getattr(obj, f)
            row[f] = str(val) if val is not None else None
        data.append(row)

    return JsonResponse({'success': True, 'data': data})


@require_POST
def stock_key_briefing_save(request, code):
    """종목 핵심 브리핑 저장 API"""
    from datetime import date
    stock = get_object_or_404(Info, code=code)
    key_briefing = request.POST.get('key_briefing', '').strip()
    opinion = request.POST.get('my_opinion', '').strip()
    update_fields = []
    if key_briefing != (stock.key_briefing or '').strip():
        stock.key_briefing = key_briefing
        stock.key_briefing_updated_at = date.today()
        update_fields += ['key_briefing', 'key_briefing_updated_at']
    if opinion != (stock.key_briefing_opinion or '').strip():
        stock.key_briefing_opinion = opinion
        update_fields.append('key_briefing_opinion')
    if update_fields:
        stock.save(update_fields=update_fields)
    return JsonResponse({'success': True, 'updated_at': stock.key_briefing_updated_at.strftime('%Y-%m-%d') if stock.key_briefing_updated_at else ''})


@require_POST
def stock_supply_demand_analysis_save(request, code):
    """종목 수급분석 저장 API"""
    from datetime import date
    stock = get_object_or_404(Info, code=code)
    text = request.POST.get('supply_demand_analysis', '').strip()
    opinion = request.POST.get('my_opinion')
    update_fields = []
    if text != (stock.supply_demand_analysis or '').strip():
        stock.supply_demand_analysis = text
        stock.supply_demand_analysis_updated_at = date.today()
        update_fields += ['supply_demand_analysis', 'supply_demand_analysis_updated_at']
    if opinion is not None:
        stock.supply_demand_analysis_opinion = opinion
        update_fields.append('supply_demand_analysis_opinion')
    if update_fields:
        stock.save(update_fields=update_fields)
    return JsonResponse({'success': True, 'updated_at': stock.supply_demand_analysis_updated_at.strftime('%Y-%m-%d') if stock.supply_demand_analysis_updated_at else ''})


@require_POST
def stock_trade_save(request, code):
    """종목 매매근거 저장 API"""
    from datetime import date
    stock = get_object_or_404(Info, code=code)
    changed = False

    buy_reason = request.POST.get('buy_reason')
    if buy_reason is not None and buy_reason.strip() != (stock.buy_reason or '').strip():
        stock.buy_reason = buy_reason.strip()
        changed = True

    sell_reason = request.POST.get('sell_reason')
    if sell_reason is not None and sell_reason.strip() != (stock.sell_reason or '').strip():
        stock.sell_reason = sell_reason.strip()
        changed = True

    buy_price = request.POST.get('buy_price', '').strip()
    new_buy = int(buy_price) if buy_price else None
    if new_buy != stock.buy_price:
        stock.buy_price = new_buy
        changed = True

    sell_price = request.POST.get('sell_price', '').strip()
    new_sell = int(sell_price) if sell_price else None
    if new_sell != stock.sell_price:
        stock.sell_price = new_sell
        changed = True

    buy_price_range = request.POST.get('buy_price_range', '').strip()
    new_range = int(buy_price_range) if buy_price_range else 5
    if new_range != stock.buy_price_range:
        stock.buy_price_range = new_range
        changed = True

    if changed:
        stock.trade_updated_at = date.today()
        stock.save(update_fields=['buy_reason', 'sell_reason', 'buy_price', 'sell_price', 'buy_price_range', 'trade_updated_at'])

    return JsonResponse({'success': True, 'updated_at': stock.trade_updated_at.strftime('%Y-%m-%d') if stock.trade_updated_at else ''})


@require_POST
def stock_memo_save(request, code):
    """종목 메모 저장 API"""
    from datetime import date
    stock = get_object_or_404(Info, code=code)
    memo = request.POST.get('memo', '').strip()
    if memo != (stock.memo or '').strip():
        stock.memo = memo
        stock.memo_updated_at = date.today()
        stock.save(update_fields=['memo', 'memo_updated_at'])
    return JsonResponse({'success': True, 'updated_at': stock.memo_updated_at.strftime('%Y-%m-%d') if stock.memo_updated_at else ''})


@require_POST
def youtube_video_delete(request, video_id):
    """유튜브 영상 삭제 API"""
    from .models import YoutubeVideo

    video = get_object_or_404(YoutubeVideo, id=video_id)
    video.delete()

    return JsonResponse({'success': True})


@require_POST
def news_save(request):
    """뉴스 저장 API (검색 결과에서)"""
    from .models import News, Info

    stock_code = request.POST.get('stock_code', '').strip()
    link = request.POST.get('link', '').strip()
    title = request.POST.get('title', '').strip()
    source = request.POST.get('source', '').strip()
    published = request.POST.get('published', '').strip()

    if not stock_code or not link or not title:
        return JsonResponse({'error': '필수 정보가 누락되었습니다.'}, status=400)

    stock = get_object_or_404(Info, code=stock_code)

    # 이미 저장된 뉴스인지 확인
    if News.objects.filter(stock=stock, link=link).exists():
        return JsonResponse({'error': '이미 저장된 뉴스입니다.'}, status=400)

    news = News.objects.create(
        stock=stock,
        title=title,
        link=link,
        source=source,
        published=published,
    )

    return JsonResponse({
        'success': True,
        'id': news.id,
        'title': news.title,
        'link': news.link,
        'source': news.source,
        'published': news.published,
    })


@require_POST
def news_save_by_link(request):
    """뉴스 저장 API (링크 또는 내용)"""
    import requests as http_requests
    from bs4 import BeautifulSoup
    from .models import News, Info

    stock_code = request.POST.get('stock_code', '').strip()
    link = request.POST.get('link', '').strip()
    content = request.POST.get('content', '').strip()

    if not stock_code or (not link and not content):
        return JsonResponse({'error': '링크 또는 내용을 입력해 주세요.'}, status=400)

    stock = get_object_or_404(Info, code=stock_code)

    if link and News.objects.filter(stock=stock, link=link).exists():
        return JsonResponse({'error': '이미 저장된 링크입니다.'}, status=400)

    title = ''
    source = ''
    published = ''

    if link:
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            }
            response = http_requests.get(link, headers=headers, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            og_title = soup.find('meta', property='og:title')
            if og_title and og_title.get('content'):
                title = og_title['content']
            elif soup.title:
                title = soup.title.string or ''
            title = title.strip()

            og_site = soup.find('meta', property='og:site_name')
            if og_site and og_site.get('content'):
                source = og_site['content']

            date_metas = [
                ('meta', {'property': 'article:published_time'}),
                ('meta', {'property': 'og:article:published_time'}),
                ('meta', {'name': 'article:published_time'}),
                ('meta', {'name': 'publishdate'}),
                ('meta', {'name': 'date'}),
                ('meta', {'property': 'og:regDate'}),
            ]
            for tag, attrs in date_metas:
                meta = soup.find(tag, attrs)
                if meta and meta.get('content'):
                    published = meta['content'][:10]
                    break

            if not published:
                import json
                for script in soup.find_all('script', type='application/ld+json'):
                    try:
                        data = json.loads(script.string or '')
                        if isinstance(data, dict):
                            date_val = data.get('datePublished') or data.get('dateCreated')
                            if date_val:
                                published = str(date_val)[:10]
                                break
                        elif isinstance(data, list):
                            for item in data:
                                if isinstance(item, dict):
                                    date_val = item.get('datePublished') or item.get('dateCreated')
                                    if date_val:
                                        published = str(date_val)[:10]
                                        break
                    except:
                        pass
        except Exception as e:
            if not content:
                return JsonResponse({'error': f'뉴스 정보를 가져오는 중 오류: {str(e)}'}, status=500)

    if link:
        news = News.objects.create(
            stock=stock,
            title=title,
            link=link,
            content=content,
            source=source,
            published=published,
        )
    else:
        news = News.objects.create(
            stock=stock,
            title='',
            link='',
            content='',
            summary=content,
            source=source,
            published=published,
        )

    return JsonResponse({
        'success': True,
        'id': news.id,
        'title': news.title,
        'link': news.link,
        'content': news.content,
        'summary': news.summary,
        'source': news.source,
        'published': news.published,
    })


@require_POST
def news_delete(request, news_id):
    """뉴스 삭제 API"""
    from .models import News

    news = get_object_or_404(News, id=news_id)
    news.delete()

    return JsonResponse({'success': True})


def news_summary(request, news_id):
    """뉴스 요약 페이지"""
    from .models import News, SystemSetting

    news = get_object_or_404(News, id=news_id)

    if request.method == 'POST':
        news.summary = request.POST.get('summary', '')
        news.my_opinion = request.POST.get('my_opinion', '')
        news.save()

    prompt_summary = SystemSetting.objects.filter(key='prompt_summary').values_list('value', flat=True).first() or ''

    return render(request, 'stocks/news_summary.html', {
        'news': news,
        'prompt_summary': prompt_summary,
    })


def report_summary(request, report_id):
    """애널리스트 리포트 요약 페이지"""
    from .models import Report, SystemSetting

    report = get_object_or_404(Report, id=report_id)

    if request.method == 'POST':
        report.summary = request.POST.get('summary', '')
        report.report_url = request.POST.get('report_url', '')
        report.news_url = request.POST.get('news_url', '')
        report.my_opinion = request.POST.get('my_opinion', '')

        # 파일 업로드 처리
        if 'file' in request.FILES:
            uploaded_file = request.FILES['file']
            # 기존 파일 삭제
            if report.file:
                report.file.delete(save=False)
            report.file = uploaded_file

        report.save()
        from django.contrib import messages
        messages.success(request, '저장되었습니다.')
        return redirect('stocks:report_summary', report_id=report_id)

    # 프롬프트 가져오기
    saved_prompt = ''
    try:
        setting = SystemSetting.objects.get(key='prompt_report_summary')
        saved_prompt = setting.value
    except SystemSetting.DoesNotExist:
        pass

    prompt_summary = SystemSetting.objects.filter(key='prompt_summary').values_list('value', flat=True).first() or ''

    return render(request, 'stocks/report_summary.html', {
        'report': report,
        'saved_prompt': saved_prompt,
        'prompt_summary': prompt_summary,
    })


@require_POST
def report_file_delete(request, report_id):
    """애널리스트 리포트 첨부파일 삭제 API"""
    from .models import Report

    report = get_object_or_404(Report, id=report_id)

    if report.file:
        report.file.delete(save=False)
        report.file = None
        report.save()

    return JsonResponse({'success': True})


def uploaded_report_summary_page(request, report_id):
    """파일 업로드 리포트 요약 페이지"""
    from .models import StockUploadedReport, SystemSetting

    report = get_object_or_404(StockUploadedReport, id=report_id)

    if request.method == 'POST':
        report.summary = request.POST.get('summary', '')
        report.report_url = request.POST.get('report_url', '')
        report.news_url = request.POST.get('news_url', '')
        report.my_opinion = request.POST.get('my_opinion', '')
        report.save()
        messages.success(request, '저장되었습니다.')
        return redirect('stocks:uploaded_report_summary_page', report_id=report_id)

    prompt_summary = SystemSetting.objects.filter(key='prompt_summary').values_list('value', flat=True).first() or ''

    return render(request, 'stocks/uploaded_report_summary.html', {
        'report': report,
        'prompt_summary': prompt_summary,
    })


@require_POST
def telegram_message_save(request):
    """텔레그램 메시지 저장 API"""
    from .models import TelegramMessage, Info

    stock_code = request.POST.get('stock_code', '').strip()
    channel = request.POST.get('channel', '').strip()
    channel_name = request.POST.get('channel_name', '').strip()
    date = request.POST.get('date', '').strip()
    time = request.POST.get('time', '').strip()
    text = request.POST.get('text', '').strip()

    if not stock_code or not channel or not date or not time or not text:
        return JsonResponse({'error': '필수 정보가 누락되었습니다.'}, status=400)

    stock = get_object_or_404(Info, code=stock_code)

    # 이미 저장된 메시지인지 확인 (channel + date + time으로 중복 체크)
    if TelegramMessage.objects.filter(stock=stock, channel=channel, date=date, time=time).exists():
        return JsonResponse({'error': '이미 저장된 메시지입니다.'}, status=400)

    msg = TelegramMessage.objects.create(
        stock=stock,
        channel=channel,
        channel_name=channel_name,
        date=date,
        time=time,
        text=text,
    )

    return JsonResponse({
        'success': True,
        'id': msg.id,
        'channel': msg.channel,
        'channel_name': msg.channel_name,
        'date': msg.date,
        'time': msg.time,
        'text': msg.text,
    })


@require_POST
def telegram_message_delete(request, message_id):
    """텔레그램 메시지 삭제 API"""
    from .models import TelegramMessage

    msg = get_object_or_404(TelegramMessage, id=message_id)
    msg.delete()

    return JsonResponse({'success': True})


def telegram_summary(request, message_id):
    """텔레그램 메시지 요약 페이지"""
    from .models import TelegramMessage

    msg = get_object_or_404(TelegramMessage, id=message_id)

    if request.method == 'POST':
        msg.summary = request.POST.get('summary', '')
        msg.save()
        return redirect('stocks:telegram_summary', message_id=message_id)

    return render(request, 'stocks/telegram_summary.html', {
        'message': msg,
    })


@require_POST
def refresh_market_trend(request, market):
    """시장 투자동향 새로고침 API"""
    import requests
    from bs4 import BeautifulSoup

    MARKET_CODES = {
        'KOSPI': '01',
        'KOSDAQ': '02',
        'FUTURES': '03',
    }

    market = market.upper()
    if market not in MARKET_CODES:
        return JsonResponse({'error': f'지원하지 않는 시장: {market}'}, status=400)

    sosok = MARKET_CODES[market]
    bizdate = datetime.now().strftime('%Y%m%d')

    def parse_number(text):
        if not text:
            return 0
        cleaned = text.replace(',', '').replace('+', '').strip()
        try:
            return int(cleaned)
        except ValueError:
            return 0

    def fetch_page(page):
        url = f'https://finance.naver.com/sise/investorDealTrendDay.naver?bizdate={bizdate}&sosok={sosok}&page={page}'
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            response.encoding = 'euc-kr'

            soup = BeautifulSoup(response.text, 'html.parser')
            table = soup.select_one('table.type_1')
            if not table:
                return []

            rows = []
            tbody = table.select_one('tbody')
            all_trs = tbody.select('tr') if tbody else table.select('tr')

            for tr in all_trs:
                tds = tr.select('td')
                if len(tds) < 4:
                    continue

                date_text = tds[0].get_text(strip=True)
                if not date_text or not date_text[0].isdigit():
                    continue

                rows.append({
                    'date': date_text,
                    'individual': parse_number(tds[1].get_text(strip=True)) if len(tds) > 1 else 0,
                    'foreign': parse_number(tds[2].get_text(strip=True)) if len(tds) > 2 else 0,
                    'institution': parse_number(tds[3].get_text(strip=True)) if len(tds) > 3 else 0,
                    'financial_investment': parse_number(tds[4].get_text(strip=True)) if len(tds) > 4 else 0,
                    'insurance': parse_number(tds[5].get_text(strip=True)) if len(tds) > 5 else 0,
                    'trust': parse_number(tds[6].get_text(strip=True)) if len(tds) > 6 else 0,
                    'bank': parse_number(tds[7].get_text(strip=True)) if len(tds) > 7 else 0,
                    'other_financial': parse_number(tds[8].get_text(strip=True)) if len(tds) > 8 else 0,
                    'pension_fund': parse_number(tds[9].get_text(strip=True)) if len(tds) > 9 else 0,
                    'other_corporation': parse_number(tds[10].get_text(strip=True)) if len(tds) > 10 else 0,
                })

            return rows
        except Exception:
            return []

    # 1페이지만 가져와서 최신 데이터 업데이트
    all_data = fetch_page(1)

    created_count = 0
    updated_count = 0

    for row in all_data:
        try:
            date = datetime.strptime(row['date'], '%y.%m.%d').date()

            obj, created = MarketTrend.objects.update_or_create(
                market=market,
                date=date,
                defaults={
                    'individual': row['individual'],
                    'foreign': row['foreign'],
                    'institution': row['institution'],
                    'financial_investment': row['financial_investment'],
                    'insurance': row['insurance'],
                    'trust': row['trust'],
                    'bank': row['bank'],
                    'other_financial': row['other_financial'],
                    'pension_fund': row['pension_fund'],
                    'other_corporation': row['other_corporation'],
                }
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

        except Exception:
            pass

    # 업데이트된 데이터 반환 (테이블용 20개, 차트용 120개)
    trends = list(MarketTrend.objects.filter(market=market).order_by('-date')[:120])

    # 테이블 데이터 (최근 20개)
    table_data = [
        {
            'date': t.date.strftime('%m.%d'),
            'individual': t.individual,
            'foreign': t.foreign,
            'institution': t.institution,
            'financial_investment': t.financial_investment,
            'insurance': t.insurance,
            'trust': t.trust,
            'bank': t.bank,
            'other_financial': t.other_financial,
            'pension_fund': t.pension_fund,
            'other_corporation': t.other_corporation,
        }
        for t in trends[:20]
    ]

    # 누적 차트 데이터
    trends.reverse()
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

    return JsonResponse({
        'success': True,
        'market': market,
        'created': created_count,
        'updated': updated_count,
        'table_data': table_data,
        'chart_data': chart_data,
    })


@require_POST
def refresh_sector(request, market):
    """업종별 순매수 새로고침 API (키움 API ka10051)"""
    import requests
    from .models import Sector, DailyChart
    from .utils import get_valid_token

    market = market.upper()
    if market not in ['KOSPI', 'KOSDAQ']:
        return JsonResponse({'error': f'지원하지 않는 시장: {market}'}, status=400)

    # 토큰 가져오기 (없거나 만료시 자동 갱신)
    token = get_valid_token()
    if not token:
        return JsonResponse({'error': '토큰 발급 실패. 키움 API 설정을 확인하세요.'}, status=400)

    # 최근 거래일 가져오기
    latest_date = DailyChart.objects.values_list('date', flat=True).order_by('-date').first()
    if not latest_date:
        return JsonResponse({'error': 'DailyChart 데이터가 없습니다.'}, status=400)

    date_str = latest_date.strftime('%Y%m%d')
    mrkt_tp = '0' if market == 'KOSPI' else '1'

    # API 호출
    url = 'https://api.kiwoom.com/api/dostk/sect'
    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'authorization': f'Bearer {token}',
        'api-id': 'ka10051',
    }
    params = {
        'mrkt_tp': mrkt_tp,
        'amt_qty_tp': '0',
        'base_dt': date_str,
        'stex_tp': '1',
    }

    def parse_number(value):
        if not value:
            return 0
        cleaned = str(value).strip().replace(',', '').replace('+', '')
        try:
            return int(cleaned)
        except (ValueError, TypeError):
            return 0

    try:
        response = requests.post(url, headers=headers, json=params, timeout=10)
        if response.status_code != 200:
            return JsonResponse({'error': f'API 오류: {response.status_code}'}, status=500)

        response_data = response.json()

        # 데이터 키 찾기
        data_key = None
        for key in ['inds_netprps', 'data', 'result', 'output']:
            if key in response_data and isinstance(response_data[key], list):
                data_key = key
                break

        if not data_key or not response_data[data_key]:
            return JsonResponse({'error': '데이터가 없습니다.'}, status=400)

        sector_list = response_data[data_key]
        saved_count = 0

        for item in sector_list:
            Sector.objects.update_or_create(
                code=item.get('inds_cd'),
                date=latest_date,
                market=market,
                defaults={
                    'name': item.get('inds_nm', ''),
                    'individual_net_buying': parse_number(item.get('ind_netprps')),
                    'foreign_net_buying': parse_number(item.get('frgnr_netprps')),
                    'institution_net_buying': parse_number(item.get('orgn_netprps')),
                    'securities_net_buying': parse_number(item.get('sc_netprps')),
                    'insurance_net_buying': parse_number(item.get('insrnc_netprps')),
                    'investment_trust_net_buying': parse_number(item.get('invtrt_netprps')),
                    'bank_net_buying': parse_number(item.get('bank_netprps')),
                    'pension_fund_net_buying': parse_number(item.get('jnsinkm_netprps')),
                    'private_fund_net_buying': parse_number(item.get('samo_fund_netprps')),
                    'other_corporation_net_buying': parse_number(item.get('etc_corp_netprps')),
                }
            )
            saved_count += 1

        # 업데이트된 데이터 반환
        sectors = Sector.objects.filter(market=market, date=latest_date).order_by('code')
        table_data = [
            {
                'code': s.code,
                'name': s.name,
                'individual_net_buying': s.individual_net_buying,
                'foreign_net_buying': s.foreign_net_buying,
                'institution_net_buying': s.institution_net_buying,
                'securities_net_buying': s.securities_net_buying,
                'insurance_net_buying': s.insurance_net_buying,
                'investment_trust_net_buying': s.investment_trust_net_buying,
                'bank_net_buying': s.bank_net_buying,
                'pension_fund_net_buying': s.pension_fund_net_buying,
                'private_fund_net_buying': s.private_fund_net_buying,
                'other_corporation_net_buying': s.other_corporation_net_buying,
            }
            for s in sectors
        ]

        return JsonResponse({
            'success': True,
            'market': market,
            'date': latest_date.strftime('%m.%d'),
            'saved': saved_count,
            'table_data': table_data,
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_POST
def refresh_stock(request, code):
    """종목 정보 새로고침 API (기본정보 + 수급 + 공매도)"""
    import requests
    from decimal import Decimal, InvalidOperation
    from datetime import timedelta
    from .models import Info, InvestorTrend, ShortSelling
    from .utils import get_valid_token

    try:
        stock = Info.objects.get(code=code)
    except Info.DoesNotExist:
        return JsonResponse({'error': '종목을 찾을 수 없습니다.'}, status=404)

    # 토큰 가져오기
    token = get_valid_token()
    if not token:
        return JsonResponse({'error': '토큰 발급 실패. 키움 API 설정을 확인하세요.'}, status=400)

    results = {}

    def parse_int(value, absolute=False):
        if not value:
            return None
        try:
            result = int(str(value).replace(',', '').replace('+', ''))
            return abs(result) if absolute else result
        except (ValueError, AttributeError):
            return None

    def parse_decimal(value):
        if not value:
            return None
        try:
            return Decimal(str(value).replace(',', '').replace('+', ''))
        except (InvalidOperation, AttributeError):
            return None

    # 1. 기본정보 (ka10001)
    try:
        url = 'https://api.kiwoom.com/api/dostk/stkinfo'
        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'authorization': f'Bearer {token}',
            'cont-yn': 'N',
            'next-key': '',
            'api-id': 'ka10001',
        }
        params = {'stk_cd': code}

        response = requests.post(url, headers=headers, json=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            stock.current_price = parse_int(data.get('cur_prc'), absolute=True)
            stock.price_change = parse_int(data.get('pred_pre'))
            stock.change_rate = parse_decimal(data.get('flu_rt'))
            stock.volume = parse_int(data.get('trde_qty'))
            stock.market_cap = parse_int(data.get('mac'))
            stock.per = parse_decimal(data.get('per'))
            stock.pbr = parse_decimal(data.get('pbr'))
            stock.save()
            results['info'] = 'success'
        else:
            results['info'] = f'error: {response.status_code}'
    except Exception as e:
        results['info'] = f'error: {str(e)}'

    # 2. 투자자 매매동향 (ka10059)
    try:
        today = datetime.now().strftime('%Y%m%d')
        url = 'https://api.kiwoom.com/api/dostk/stkinfo'
        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'authorization': f'Bearer {token}',
            'cont-yn': 'N',
            'next-key': '',
            'api-id': 'ka10059',
        }
        params = {
            'dt': today,
            'stk_cd': code,
            'amt_qty_tp': '1',
            'trde_tp': '0',
            'unit_tp': '1000',
        }

        response = requests.post(url, headers=headers, json=params, timeout=10)
        if response.status_code == 200:
            response_data = response.json()
            data_key = None
            for key in ['stk_invsr_orgn', 'invsr_stk_daly', 'stk_invsr_daly', 'data', 'result', 'output']:
                if key in response_data and isinstance(response_data[key], list):
                    data_key = key
                    break

            if data_key and response_data[data_key]:
                all_data = response_data[data_key]
                latest_date = max(item.get('dt', '') for item in all_data)
                latest_data = [item for item in all_data if item.get('dt') == latest_date]

                for item in latest_data:
                    date = datetime.strptime(item['dt'], '%Y%m%d').date()
                    InvestorTrend.objects.update_or_create(
                        stock=stock,
                        date=date,
                        defaults={
                            'individual': parse_int(item.get('ind_invsr')) or 0,
                            'foreign': parse_int(item.get('frgnr_invsr')) or 0,
                            'institution': parse_int(item.get('orgn')) or 0,
                            'domestic_foreign': parse_int(item.get('natfor')) or 0,
                            'financial': parse_int(item.get('fnnc_invt')) or 0,
                            'insurance': parse_int(item.get('insrnc')) or 0,
                            'investment_trust': parse_int(item.get('invtrt')) or 0,
                            'other_finance': parse_int(item.get('etc_fnnc')) or 0,
                            'bank': parse_int(item.get('bank')) or 0,
                            'pension_fund': parse_int(item.get('penfnd_etc')) or 0,
                            'private_fund': parse_int(item.get('samo_fund')) or 0,
                            'other_corporation': parse_int(item.get('etc_corp')) or 0,
                        }
                    )
                results['investor'] = 'success'
            else:
                results['investor'] = 'no data'
        else:
            results['investor'] = f'error: {response.status_code}'
    except Exception as e:
        results['investor'] = f'error: {str(e)}'

    # 3. 공매도 (ka10014)
    try:
        today = datetime.now()
        week_ago = today - timedelta(days=7)
        url = 'https://api.kiwoom.com/api/dostk/shsa'
        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'authorization': f'Bearer {token}',
            'cont-yn': 'N',
            'next-key': '',
            'api-id': 'ka10014',
        }
        params = {
            'stk_cd': code,
            'tm_tp': '1',
            'strt_dt': week_ago.strftime('%Y%m%d'),
            'end_dt': today.strftime('%Y%m%d'),
        }

        response = requests.post(url, headers=headers, json=params, timeout=10)
        if response.status_code == 200:
            response_data = response.json()
            data_key = None
            for key in ['shrts_trnsn', 'data', 'result', 'output']:
                if key in response_data and isinstance(response_data[key], list):
                    data_key = key
                    break

            if data_key and response_data[data_key]:
                all_data = response_data[data_key]
                dates = [item.get('dt', '') for item in all_data if item.get('dt')]
                if dates:
                    latest_date = max(dates)
                    latest_data = [item for item in all_data if item.get('dt') == latest_date]

                    for item in latest_data:
                        date = datetime.strptime(item['dt'], '%Y%m%d').date()
                        ShortSelling.objects.update_or_create(
                            stock=stock,
                            date=date,
                            defaults={
                                'trading_volume': parse_int(item.get('trde_qty')) or 0,
                                'short_volume': parse_int(item.get('shrts_qty')) or 0,
                                'cumulative_short_volume': parse_int(item.get('ovr_shrts_qty')) or 0,
                                'trading_weight': parse_decimal(item.get('trde_wght')) or Decimal('0'),
                                'short_trading_value': parse_int(item.get('shrts_trde_prica')) or 0,
                                'short_average_price': parse_int(item.get('shrts_avg_pric')) or 0,
                            }
                        )
                    results['short'] = 'success'
                else:
                    results['short'] = 'no data'
            else:
                results['short'] = 'no data'
        else:
            results['short'] = f'error: {response.status_code}'
    except Exception as e:
        results['short'] = f'error: {str(e)}'

    # 업데이트된 데이터 반환
    stock.refresh_from_db()

    return JsonResponse({
        'success': True,
        'results': results,
        'data': {
            'current_price': stock.current_price,
            'price_change': stock.price_change,
            'change_rate': float(stock.change_rate) if stock.change_rate else None,
            'volume': stock.volume,
            'market_cap': stock.market_cap,
            'per': float(stock.per) if stock.per else None,
            'pbr': float(stock.pbr) if stock.pbr else None,
        }
    })


@require_POST
def fetch_investor_trend(request, code):
    """수급 데이터 가져오기 API (6개월)"""
    import requests
    from datetime import timedelta
    from .models import Info, InvestorTrend
    from .utils import get_valid_token

    try:
        stock = Info.objects.get(code=code)
    except Info.DoesNotExist:
        return JsonResponse({'error': '종목을 찾을 수 없습니다.'}, status=404)

    token = get_valid_token()
    if not token:
        return JsonResponse({'error': '토큰 발급 실패. 키움 API 설정을 확인하세요.'}, status=400)

    def parse_int(value):
        if not value:
            return 0
        try:
            return int(str(value).strip().replace(',', '').replace('+', ''))
        except (ValueError, AttributeError):
            return 0

    six_months_ago = datetime.now() - timedelta(days=180)
    cutoff_date = six_months_ago.strftime('%Y%m%d')
    today = datetime.now().strftime('%Y%m%d')

    all_data = []
    cont_yn = 'N'
    next_key = ''

    # 연속조회로 6개월 데이터 수집
    for _ in range(10):  # 최대 10번 반복
        url = 'https://api.kiwoom.com/api/dostk/stkinfo'
        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'authorization': f'Bearer {token}',
            'cont-yn': cont_yn,
            'next-key': next_key,
            'api-id': 'ka10059',
        }
        params = {
            'dt': today,
            'stk_cd': code,
            'amt_qty_tp': '1',
            'trde_tp': '0',
            'unit_tp': '1000',
        }

        try:
            response = requests.post(url, headers=headers, json=params, timeout=10)
            if response.status_code != 200:
                break

            response_data = response.json()
            data_key = None
            for key in ['stk_invsr_orgn', 'invsr_stk_daly', 'stk_invsr_daly', 'data', 'result', 'output']:
                if key in response_data and isinstance(response_data[key], list):
                    data_key = key
                    break

            if not data_key:
                break

            current_batch = response_data[data_key]
            filtered = [item for item in current_batch if item.get('dt', '') >= cutoff_date]
            all_data.extend(filtered)

            # 가장 오래된 날짜 확인
            if current_batch:
                oldest_date = min(item.get('dt', '') for item in current_batch)
                if oldest_date < cutoff_date:
                    break

            # 연속조회 확인
            if response.headers.get('cont-yn') == 'Y' and response.headers.get('next-key'):
                cont_yn = 'Y'
                next_key = response.headers.get('next-key')
            else:
                break

        except Exception:
            break

    # DB 저장
    created_count = 0
    updated_count = 0

    for item in all_data:
        try:
            date = datetime.strptime(item['dt'], '%Y%m%d').date()
            _, created = InvestorTrend.objects.update_or_create(
                stock=stock,
                date=date,
                defaults={
                    'individual': parse_int(item.get('ind_invsr')),
                    'foreign': parse_int(item.get('frgnr_invsr')),
                    'institution': parse_int(item.get('orgn')),
                    'domestic_foreign': parse_int(item.get('natfor')),
                    'financial': parse_int(item.get('fnnc_invt')),
                    'insurance': parse_int(item.get('insrnc')),
                    'investment_trust': parse_int(item.get('invtrt')),
                    'other_finance': parse_int(item.get('etc_fnnc')),
                    'bank': parse_int(item.get('bank')),
                    'pension_fund': parse_int(item.get('penfnd_etc')),
                    'private_fund': parse_int(item.get('samo_fund')),
                    'other_corporation': parse_int(item.get('etc_corp')),
                }
            )
            if created:
                created_count += 1
            else:
                updated_count += 1
        except Exception:
            pass

    return JsonResponse({
        'success': True,
        'created': created_count,
        'updated': updated_count,
        'total': len(all_data),
    })


@require_POST
def fetch_short_selling(request, code):
    """공매도 데이터 가져오기 API (60일)"""
    import requests
    from decimal import Decimal
    from datetime import timedelta
    from .models import Info, ShortSelling
    from .utils import get_valid_token

    try:
        stock = Info.objects.get(code=code)
    except Info.DoesNotExist:
        return JsonResponse({'error': '종목을 찾을 수 없습니다.'}, status=404)

    token = get_valid_token()
    if not token:
        return JsonResponse({'error': '토큰 발급 실패. 키움 API 설정을 확인하세요.'}, status=400)

    def parse_int(value):
        if not value:
            return 0
        try:
            return int(str(value).strip().replace(',', '').replace('+', ''))
        except (ValueError, AttributeError):
            return 0

    def parse_decimal(value):
        if not value:
            return Decimal('0')
        try:
            return Decimal(str(value).strip().replace(',', ''))
        except Exception:
            return Decimal('0')

    sixty_days_ago = datetime.now() - timedelta(days=60)
    cutoff_date = sixty_days_ago.strftime('%Y%m%d')
    today = datetime.now().strftime('%Y%m%d')

    all_data = []
    cont_yn = 'N'
    next_key = ''

    # 연속조회로 60일 데이터 수집
    for _ in range(5):  # 최대 5번 반복
        url = 'https://api.kiwoom.com/api/dostk/shsa'
        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'authorization': f'Bearer {token}',
            'cont-yn': cont_yn,
            'next-key': next_key,
            'api-id': 'ka10014',
        }
        params = {
            'stk_cd': code,
            'tm_tp': '1',
            'strt_dt': cutoff_date,
            'end_dt': today,
        }

        try:
            response = requests.post(url, headers=headers, json=params, timeout=10)
            if response.status_code != 200:
                break

            response_data = response.json()
            data_key = None
            for key in ['shrts_trnsn', 'data', 'result', 'output']:
                if key in response_data and isinstance(response_data[key], list):
                    data_key = key
                    break

            if not data_key:
                break

            current_batch = response_data[data_key]
            filtered = [item for item in current_batch if item.get('dt', '') >= cutoff_date]
            all_data.extend(filtered)

            # 연속조회 확인
            if response.headers.get('cont-yn') == 'Y' and response.headers.get('next-key'):
                cont_yn = 'Y'
                next_key = response.headers.get('next-key')
            else:
                break

        except Exception:
            break

    # DB 저장
    created_count = 0
    updated_count = 0

    for item in all_data:
        try:
            date = datetime.strptime(item['dt'], '%Y%m%d').date()
            _, created = ShortSelling.objects.update_or_create(
                stock=stock,
                date=date,
                defaults={
                    'trading_volume': parse_int(item.get('trde_qty')),
                    'short_volume': parse_int(item.get('shrts_qty')),
                    'cumulative_short_volume': parse_int(item.get('ovr_shrts_qty')),
                    'trading_weight': parse_decimal(item.get('trde_wght')),
                    'short_trading_value': parse_int(item.get('shrts_trde_prica')),
                    'short_average_price': parse_int(item.get('shrts_avg_pric')),
                }
            )
            if created:
                created_count += 1
            else:
                updated_count += 1
        except Exception:
            pass

    return JsonResponse({
        'success': True,
        'created': created_count,
        'updated': updated_count,
        'total': len(all_data),
    })


@require_GET
def get_setting(request):
    """시스템 설정 조회"""
    from .models import SystemSetting
    key = request.GET.get('key', '')
    if not key:
        return JsonResponse({'success': False, 'error': '키가 필요합니다.'})
    try:
        setting = SystemSetting.objects.get(key=key)
        return JsonResponse({'success': True, 'value': setting.value})
    except SystemSetting.DoesNotExist:
        return JsonResponse({'success': True, 'value': ''})


@require_POST
def save_setting(request):
    """시스템 설정 저장"""
    from .models import SystemSetting

    key = request.POST.get('key')
    value = request.POST.get('value', '')

    if not key:
        return JsonResponse({'success': False, 'error': '키가 필요합니다.'})

    SystemSetting.objects.update_or_create(
        key=key,
        defaults={'value': value}
    )

    return JsonResponse({'success': True})


# ============ 리서치 프롬프트 ============

def research_prompt_list(request):
    """리서치 프롬프트 목록 조회"""
    from .models import ResearchPrompt

    prompts = ResearchPrompt.objects.all()
    data = [{
        'id': p.id,
        'question': p.question,
        'prompt': p.prompt,
        'order': p.order,
        'needs_attachment': p.needs_attachment
    } for p in prompts]

    return JsonResponse({'success': True, 'prompts': data})


@require_POST
def research_prompt_add(request):
    """리서치 프롬프트 추가"""
    from django.db.models import Max
    from .models import ResearchPrompt

    question = request.POST.get('question', '').strip()
    prompt = request.POST.get('prompt', '').strip()
    needs_attachment = request.POST.get('needs_attachment') == 'true'

    if not question:
        return JsonResponse({'success': False, 'error': '질문을 입력해주세요.'})

    # 순서는 가장 마지막으로
    max_order = ResearchPrompt.objects.aggregate(Max('order'))['order__max'] or 0
    obj = ResearchPrompt.objects.create(
        question=question,
        prompt=prompt,
        order=max_order + 1,
        needs_attachment=needs_attachment
    )

    return JsonResponse({
        'success': True,
        'id': obj.id,
        'question': obj.question,
        'prompt': obj.prompt,
        'order': obj.order,
        'needs_attachment': obj.needs_attachment
    })


@require_POST
def research_prompt_update(request, prompt_id):
    """리서치 프롬프트 수정"""
    from .models import ResearchPrompt

    try:
        obj = ResearchPrompt.objects.get(id=prompt_id)
    except ResearchPrompt.DoesNotExist:
        return JsonResponse({'success': False, 'error': '프롬프트를 찾을 수 없습니다.'})

    question = request.POST.get('question', '').strip()
    prompt = request.POST.get('prompt', '').strip()
    needs_attachment = request.POST.get('needs_attachment') == 'true'

    if not question:
        return JsonResponse({'success': False, 'error': '질문을 입력해주세요.'})

    obj.question = question
    obj.prompt = prompt
    obj.needs_attachment = needs_attachment
    obj.save()

    return JsonResponse({'success': True})


@require_POST
def research_prompt_delete(request, prompt_id):
    """리서치 프롬프트 삭제"""
    from .models import ResearchPrompt

    try:
        obj = ResearchPrompt.objects.get(id=prompt_id)
        obj.delete()
        return JsonResponse({'success': True})
    except ResearchPrompt.DoesNotExist:
        return JsonResponse({'success': False, 'error': '프롬프트를 찾을 수 없습니다.'})


# ============ 퀵리포트 ============

def quick_report_list(request):
    """퀵리포트 목록 조회"""
    from .models import QuickReport

    prompts = QuickReport.objects.all()
    data = [{
        'id': p.id,
        'question': p.question,
        'prompt': p.prompt,
        'order': p.order,
        'needs_attachment': p.needs_attachment
    } for p in prompts]

    return JsonResponse({'success': True, 'prompts': data})


@require_POST
def quick_report_add(request):
    """퀵리포트 추가"""
    from django.db.models import Max
    from .models import QuickReport

    question = request.POST.get('question', '').strip()
    prompt = request.POST.get('prompt', '').strip()
    needs_attachment = request.POST.get('needs_attachment') == 'true'

    if not question:
        return JsonResponse({'success': False, 'error': '질문을 입력해주세요.'})

    max_order = QuickReport.objects.aggregate(Max('order'))['order__max'] or 0
    obj = QuickReport.objects.create(
        question=question,
        prompt=prompt,
        order=max_order + 1,
        needs_attachment=needs_attachment
    )

    return JsonResponse({
        'success': True,
        'id': obj.id,
        'question': obj.question,
        'prompt': obj.prompt,
        'order': obj.order,
        'needs_attachment': obj.needs_attachment
    })


@require_POST
def quick_report_update(request, prompt_id):
    """퀵리포트 수정"""
    from .models import QuickReport

    try:
        obj = QuickReport.objects.get(id=prompt_id)
    except QuickReport.DoesNotExist:
        return JsonResponse({'success': False, 'error': '프롬프트를 찾을 수 없습니다.'})

    question = request.POST.get('question', '').strip()
    prompt = request.POST.get('prompt', '').strip()
    needs_attachment = request.POST.get('needs_attachment') == 'true'

    if not question:
        return JsonResponse({'success': False, 'error': '질문을 입력해주세요.'})

    obj.question = question
    obj.prompt = prompt
    obj.needs_attachment = needs_attachment
    obj.save()

    return JsonResponse({'success': True})


@require_POST
def quick_report_delete(request, prompt_id):
    """퀵리포트 삭제"""
    from .models import QuickReport

    try:
        obj = QuickReport.objects.get(id=prompt_id)
        obj.delete()
        return JsonResponse({'success': True})
    except QuickReport.DoesNotExist:
        return JsonResponse({'success': False, 'error': '프롬프트를 찾을 수 없습니다.'})


# ============ 정리리포트 관리 ============

def summary_report_list(request):
    """정리리포트 목록 조회"""
    from .models import SummaryReport

    prompts = SummaryReport.objects.all()
    data = [{
        'id': p.id,
        'question': p.question,
        'prompt': p.prompt,
        'order': p.order,
        'needs_attachment': p.needs_attachment
    } for p in prompts]

    return JsonResponse({'success': True, 'prompts': data})


@require_POST
def summary_report_add(request):
    """정리리포트 추가"""
    from django.db.models import Max
    from .models import SummaryReport

    question = request.POST.get('question', '').strip()
    prompt = request.POST.get('prompt', '').strip()
    needs_attachment = request.POST.get('needs_attachment') == 'true'

    if not question:
        return JsonResponse({'success': False, 'error': '질문을 입력해주세요.'})

    max_order = SummaryReport.objects.aggregate(Max('order'))['order__max'] or 0
    obj = SummaryReport.objects.create(
        question=question,
        prompt=prompt,
        order=max_order + 1,
        needs_attachment=needs_attachment
    )

    return JsonResponse({
        'success': True,
        'id': obj.id,
        'question': obj.question,
        'prompt': obj.prompt,
        'order': obj.order,
        'needs_attachment': obj.needs_attachment
    })


@require_POST
def summary_report_update(request, prompt_id):
    """정리리포트 수정"""
    from .models import SummaryReport

    try:
        obj = SummaryReport.objects.get(id=prompt_id)
    except SummaryReport.DoesNotExist:
        return JsonResponse({'success': False, 'error': '프롬프트를 찾을 수 없습니다.'})

    question = request.POST.get('question', '').strip()
    prompt = request.POST.get('prompt', '').strip()
    needs_attachment = request.POST.get('needs_attachment') == 'true'

    if not question:
        return JsonResponse({'success': False, 'error': '질문을 입력해주세요.'})

    obj.question = question
    obj.prompt = prompt
    obj.needs_attachment = needs_attachment
    obj.save()

    return JsonResponse({'success': True})


@require_POST
def summary_report_delete(request, prompt_id):
    """정리리포트 삭제"""
    from .models import SummaryReport

    try:
        obj = SummaryReport.objects.get(id=prompt_id)
        obj.delete()
        return JsonResponse({'success': True})
    except SummaryReport.DoesNotExist:
        return JsonResponse({'success': False, 'error': '프롬프트를 찾을 수 없습니다.'})


# ============ 대기 관리 ============

def waiting_report_list(request):
    """대기 목록 조회"""
    from .models import WaitingReport

    prompts = WaitingReport.objects.all()
    data = [{
        'id': p.id,
        'question': p.question,
        'prompt': p.prompt,
        'order': p.order,
        'needs_attachment': p.needs_attachment
    } for p in prompts]

    return JsonResponse({'success': True, 'prompts': data})


@require_POST
def waiting_report_add(request):
    """대기 추가"""
    from django.db.models import Max
    from .models import WaitingReport

    question = request.POST.get('question', '').strip()
    prompt = request.POST.get('prompt', '').strip()
    needs_attachment = request.POST.get('needs_attachment') == 'true'

    if not question:
        return JsonResponse({'success': False, 'error': '질문을 입력해주세요.'})

    max_order = WaitingReport.objects.aggregate(Max('order'))['order__max'] or 0
    obj = WaitingReport.objects.create(
        question=question,
        prompt=prompt,
        order=max_order + 1,
        needs_attachment=needs_attachment
    )

    return JsonResponse({
        'success': True,
        'id': obj.id,
        'question': obj.question,
        'prompt': obj.prompt,
        'order': obj.order,
        'needs_attachment': obj.needs_attachment
    })


@require_POST
def waiting_report_update(request, prompt_id):
    """대기 수정"""
    from .models import WaitingReport

    try:
        obj = WaitingReport.objects.get(id=prompt_id)
    except WaitingReport.DoesNotExist:
        return JsonResponse({'success': False, 'error': '프롬프트를 찾을 수 없습니다.'})

    question = request.POST.get('question', '').strip()
    prompt = request.POST.get('prompt', '').strip()
    needs_attachment = request.POST.get('needs_attachment') == 'true'

    if not question:
        return JsonResponse({'success': False, 'error': '질문을 입력해주세요.'})

    obj.question = question
    obj.prompt = prompt
    obj.needs_attachment = needs_attachment
    obj.save()

    return JsonResponse({'success': True})


@require_POST
def waiting_report_delete(request, prompt_id):
    """대기 삭제"""
    from .models import WaitingReport

    try:
        obj = WaitingReport.objects.get(id=prompt_id)
        obj.delete()
        return JsonResponse({'success': True})
    except WaitingReport.DoesNotExist:
        return JsonResponse({'success': False, 'error': '프롬프트를 찾을 수 없습니다.'})


# ============ 섹터 텔레그램 메시지 ============

@require_POST
def sector_telegram_message_save(request):
    """섹터 텔레그램 메시지 저장"""
    from .models import CustomSector, SectorTelegramMessage

    sector_id = request.POST.get('sector_id')
    channel = request.POST.get('channel', '')
    channel_name = request.POST.get('channel_name', '')
    date = request.POST.get('date', '')
    time = request.POST.get('time', '')
    text = request.POST.get('text', '')

    if not sector_id or not channel or not date or not time or not text:
        return JsonResponse({'error': '필수 항목이 누락되었습니다.'})

    try:
        sector = CustomSector.objects.get(id=sector_id)
    except CustomSector.DoesNotExist:
        return JsonResponse({'error': '섹터를 찾을 수 없습니다.'})

    # 중복 체크
    exists = SectorTelegramMessage.objects.filter(
        sector=sector,
        channel=channel,
        date=date,
        time=time
    ).exists()

    if exists:
        return JsonResponse({'error': '이미 저장된 메시지입니다.'})

    msg = SectorTelegramMessage.objects.create(
        sector=sector,
        channel=channel,
        channel_name=channel_name,
        date=date,
        time=time,
        text=text
    )

    return JsonResponse({
        'success': True,
        'id': msg.id,
        'channel': msg.channel,
        'channel_name': msg.channel_name,
        'date': msg.date,
        'time': msg.time,
        'text': msg.text,
    })


@require_POST
def sector_telegram_message_delete(request, message_id):
    """섹터 텔레그램 메시지 삭제"""
    from .models import SectorTelegramMessage

    try:
        msg = SectorTelegramMessage.objects.get(id=message_id)
        msg.delete()
        return JsonResponse({'success': True})
    except SectorTelegramMessage.DoesNotExist:
        return JsonResponse({'success': False, 'error': '메시지를 찾을 수 없습니다.'})


# ============ 섹터 뉴스 ============

@require_POST
def sector_news_save(request):
    """섹터 뉴스 저장 (검색 결과에서)"""
    from .models import CustomSector, SectorNews

    sector_id = request.POST.get('sector_id')
    title = request.POST.get('title', '')
    link = request.POST.get('link', '')
    source = request.POST.get('source', '')
    published = request.POST.get('published', '')

    if not sector_id or not title or not link:
        return JsonResponse({'error': '필수 항목이 누락되었습니다.'})

    try:
        sector = CustomSector.objects.get(id=sector_id)
    except CustomSector.DoesNotExist:
        return JsonResponse({'error': '섹터를 찾을 수 없습니다.'})

    # 중복 체크
    if SectorNews.objects.filter(sector=sector, link=link).exists():
        return JsonResponse({'error': '이미 저장된 뉴스입니다.'})

    news = SectorNews.objects.create(
        sector=sector,
        title=title,
        link=link,
        source=source,
        published=published
    )

    return JsonResponse({
        'success': True,
        'id': news.id,
        'title': news.title,
        'link': news.link,
        'source': news.source,
        'published': news.published,
    })


@require_POST
def sector_news_save_by_link(request):
    """섹터 뉴스 저장 (링크로 직접)"""
    import requests as http_requests
    from bs4 import BeautifulSoup
    from .models import CustomSector, SectorNews

    sector_id = request.POST.get('sector_id')
    link = request.POST.get('link', '').strip()
    content = request.POST.get('content', '').strip()

    if not sector_id or (not link and not content):
        return JsonResponse({'error': '링크 또는 내용을 입력해 주세요.'})

    try:
        sector = CustomSector.objects.get(id=sector_id)
    except CustomSector.DoesNotExist:
        return JsonResponse({'error': '섹터를 찾을 수 없습니다.'})

    if link and SectorNews.objects.filter(sector=sector, link=link).exists():
        return JsonResponse({'error': '이미 저장된 링크입니다.'})

    title = ''
    source = ''
    published = ''

    if link:
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = http_requests.get(link, headers=headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            og_title = soup.find('meta', property='og:title')
            title = og_title['content'] if og_title else (soup.title.string if soup.title else link)

            og_site = soup.find('meta', property='og:site_name')
            source = og_site['content'] if og_site else ''

            date_metas = [
                ('meta', {'property': 'article:published_time'}),
                ('meta', {'property': 'og:article:published_time'}),
                ('meta', {'name': 'article:published_time'}),
                ('meta', {'name': 'publishdate'}),
                ('meta', {'name': 'date'}),
                ('meta', {'property': 'og:regDate'}),
            ]
            for tag, attrs in date_metas:
                meta = soup.find(tag, attrs)
                if meta and meta.get('content'):
                    published = meta['content'][:10]
                    break

            if not published:
                import json
                for script in soup.find_all('script', type='application/ld+json'):
                    try:
                        data = json.loads(script.string or '')
                        if isinstance(data, dict):
                            date_val = data.get('datePublished') or data.get('dateCreated')
                            if date_val:
                                published = str(date_val)[:10]
                                break
                        elif isinstance(data, list):
                            for item in data:
                                if isinstance(item, dict):
                                    date_val = item.get('datePublished') or item.get('dateCreated')
                                    if date_val:
                                        published = str(date_val)[:10]
                                        break
                    except:
                        pass

        except Exception as e:
            if not content:
                return JsonResponse({'error': f'페이지를 가져올 수 없습니다: {str(e)}'})

    if link:
        news = SectorNews.objects.create(
            sector=sector,
            title=title,
            link=link,
            content=content,
            source=source,
            published=published,
        )
    else:
        news = SectorNews.objects.create(
            sector=sector,
            title='',
            link='',
            content='',
            summary=content,
            source=source,
            published=published,
        )

    return JsonResponse({
        'success': True,
        'id': news.id,
        'title': news.title,
        'link': news.link,
        'content': news.content,
        'summary': news.summary,
        'source': news.source,
        'published': news.published,
    })


@require_POST
def sector_news_delete(request, news_id):
    """섹터 뉴스 삭제"""
    from .models import SectorNews

    try:
        news = SectorNews.objects.get(id=news_id)
        news.delete()
        return JsonResponse({'success': True})
    except SectorNews.DoesNotExist:
        return JsonResponse({'success': False, 'error': '뉴스를 찾을 수 없습니다.'})


def sector_news_summary(request, news_id):
    """섹터 뉴스 요약 페이지"""
    from django.contrib import messages
    from .models import SectorNews, SystemSetting

    news = get_object_or_404(SectorNews, id=news_id)

    if request.method == 'POST':
        news.summary = request.POST.get('summary', '')
        news.my_opinion = request.POST.get('my_opinion', '')
        news.save()

    prompt_summary = SystemSetting.objects.filter(key='prompt_summary').values_list('value', flat=True).first() or ''

    return render(request, 'stocks/sector_news_summary.html', {
        'news': news,
        'prompt_summary': prompt_summary,
    })


# ============ 섹터 유튜브 ============

@require_POST
def sector_youtube_video_save(request):
    """섹터 유튜브 영상 저장 API"""
    from .models import SectorYoutubeVideo, CustomSector

    sector_id = request.POST.get('sector_id', '').strip()
    video_id = request.POST.get('video_id', '').strip()
    title = request.POST.get('title', '').strip()
    channel = request.POST.get('channel', '').strip()
    thumbnail = request.POST.get('thumbnail', '').strip()
    duration = request.POST.get('duration', '').strip()
    views = request.POST.get('views', '').strip()
    published = request.POST.get('published', '').strip()

    if not sector_id or not video_id or not title:
        return JsonResponse({'error': '필수 정보가 누락되었습니다.'}, status=400)

    sector = get_object_or_404(CustomSector, id=sector_id)

    # 이미 저장된 영상인지 확인
    if SectorYoutubeVideo.objects.filter(sector=sector, video_id=video_id).exists():
        return JsonResponse({'error': '이미 저장된 영상입니다.'}, status=400)

    video = SectorYoutubeVideo.objects.create(
        sector=sector,
        video_id=video_id,
        title=title,
        channel=channel,
        thumbnail=thumbnail,
        duration=duration,
        views=views,
        published=published,
    )

    return JsonResponse({
        'success': True,
        'id': video.id,
        'video_id': video.video_id,
        'title': video.title,
    })


@require_POST
def sector_youtube_video_save_by_link(request):
    """섹터 유튜브 링크로 영상 저장 API"""
    import requests as http_requests
    import re
    import json
    from .models import SectorYoutubeVideo, CustomSector

    sector_id = request.POST.get('sector_id', '').strip()
    link = request.POST.get('link', '').strip()
    summary = request.POST.get('summary', '').strip()

    if not sector_id or not link:
        return JsonResponse({'error': '필수 정보가 누락되었습니다.'}, status=400)

    # video_id 추출
    video_id = None
    # youtube.com/watch?v=VIDEO_ID
    match = re.search(r'[?&]v=([^&]+)', link)
    if match:
        video_id = match.group(1)
    else:
        # youtu.be/VIDEO_ID
        match = re.search(r'youtu\.be/([^?&]+)', link)
        if match:
            video_id = match.group(1)
        else:
            # youtube.com/embed/VIDEO_ID
            match = re.search(r'embed/([^?&]+)', link)
            if match:
                video_id = match.group(1)
            else:
                # youtube.com/shorts/VIDEO_ID
                match = re.search(r'shorts/([^?&]+)', link)
                if match:
                    video_id = match.group(1)

    if not video_id:
        return JsonResponse({'error': '올바른 유튜브 링크가 아닙니다.'}, status=400)

    sector = get_object_or_404(CustomSector, id=sector_id)

    # 이미 저장된 영상이면 기존 id 반환 (저장 모달 등에서 바로 이동 가능)
    existing = SectorYoutubeVideo.objects.filter(sector=sector, video_id=video_id).first()
    if existing:
        return JsonResponse({'success': True, 'id': existing.id, 'duplicate': True})

    # 유튜브 페이지에서 영상 정보 가져오기
    try:
        url = f'https://www.youtube.com/watch?v={video_id}'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'ko-KR,ko;q=0.9',
        }
        response = http_requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        # ytInitialPlayerResponse에서 정보 추출
        title = ''
        channel = ''
        thumbnail = ''
        views = ''
        published = ''

        # 유니코드 이스케이프 디코딩 함수
        def decode_unicode(s):
            try:
                return json.loads(f'"{s}"')
            except:
                return s

        # 제목 추출
        title_match = re.search(r'"title":"([^"]+)"', response.text)
        if title_match:
            title = decode_unicode(title_match.group(1))

        # 채널명 추출
        channel_match = re.search(r'"ownerChannelName":"([^"]+)"', response.text)
        if channel_match:
            channel = decode_unicode(channel_match.group(1))

        # 썸네일
        thumbnail = f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg'

        # 조회수 추출
        views_match = re.search(r'"viewCount":"(\d+)"', response.text)
        if views_match:
            view_count = int(views_match.group(1))
            if view_count >= 10000:
                views = f'조회수 {view_count // 10000}만회'
            elif view_count >= 1000:
                views = f'조회수 {view_count // 1000}천회'
            else:
                views = f'조회수 {view_count}회'

        # 업로드 날짜 추출 (여러 패턴 시도)
        date_match = re.search(r'"publishDate":"(\d{4}-\d{2}-\d{2})"', response.text)
        if date_match:
            published = date_match.group(1)
        else:
            # 대체 패턴 1: uploadDate
            date_match = re.search(r'"uploadDate":"(\d{4}-\d{2}-\d{2})"', response.text)
            if date_match:
                published = date_match.group(1)
            else:
                # 대체 패턴 2: dateText (절대 날짜)
                date_match = re.search(r'"dateText":\{"simpleText":"([^"]+)"\}', response.text)
                if date_match:
                    published = date_match.group(1)
                else:
                    # 대체 패턴 3: publishedTimeText (상대 시간 "1일 전" 등)
                    date_match = re.search(r'"publishedTimeText":\{"simpleText":"([^"]+)"\}', response.text)
                    if date_match:
                        published = date_match.group(1)

        if not title:
            return JsonResponse({'error': '영상 정보를 가져올 수 없습니다.'}, status=400)

        video = SectorYoutubeVideo.objects.create(
            sector=sector,
            video_id=video_id,
            title=title,
            channel=channel,
            thumbnail=thumbnail,
            views=views,
            published=published,
            summary=summary,
        )

        return JsonResponse({
            'success': True,
            'id': video.id,
            'video_id': video.video_id,
            'title': video.title,
            'channel': video.channel,
            'thumbnail': video.thumbnail,
            'views': video.views,
            'published': video.published,
        })

    except Exception as e:
        return JsonResponse({'error': f'영상 정보를 가져오는 중 오류: {str(e)}'}, status=500)


@require_GET
def sector_youtube_video_list(request):
    """섹터 유튜브 목록 API (페이지네이션)"""
    from .models import SectorYoutubeVideo
    sector_id = request.GET.get('sector_id')
    limit = int(request.GET.get('limit', 30))
    offset = int(request.GET.get('offset', 0))
    qs = SectorYoutubeVideo.objects.filter(sector_id=sector_id)
    total = qs.count()
    videos = qs[offset:offset + limit]
    results = []
    for v in videos:
        results.append({
            'id': v.id,
            'video_id': v.video_id,
            'title': v.title,
            'channel': v.channel,
            'note': v.my_opinion,
            'summary': v.summary,
            'url': v.link,
            'date': v.created_at.strftime('%Y-%m-%d'),
        })
    return JsonResponse({'success': True, 'results': results, 'total': total, 'has_more': offset + limit < total})


@require_POST
def sector_youtube_video_update(request, video_id):
    """섹터 유튜브 영상 수정 API"""
    from .models import SectorYoutubeVideo
    video = get_object_or_404(SectorYoutubeVideo, id=video_id)
    note = request.POST.get('note')
    summary = request.POST.get('summary')
    if note is not None:
        video.my_opinion = note
    if summary is not None:
        video.summary = summary
    video.save()
    return JsonResponse({'success': True})


@require_POST
def sector_youtube_video_delete(request, video_id):
    """섹터 유튜브 영상 삭제 API"""
    from .models import SectorYoutubeVideo

    video = get_object_or_404(SectorYoutubeVideo, id=video_id)
    video.delete()

    return JsonResponse({'success': True})


def sector_youtube_summary(request, video_id):
    """섹터 유튜브 영상 요약 편집 페이지"""
    from .models import SectorYoutubeVideo, SystemSetting

    video = get_object_or_404(SectorYoutubeVideo, id=video_id)

    if request.method == 'POST':
        video.summary = request.POST.get('summary', '')
        video.my_opinion = request.POST.get('my_opinion', '')
        video.save()
        messages.success(request, '요약이 저장되었습니다.')
        return redirect('stocks:sector_youtube_summary', video_id=video_id)

    prompt_summary = SystemSetting.objects.filter(key='prompt_summary').values_list('value', flat=True).first() or ''

    return render(request, 'stocks/sector_youtube_summary.html', {
        'video': video,
        'prompt_summary': prompt_summary,
    })


# ============ 파일 업로드 리포트 (종목) ============

@require_POST
def stock_uploaded_report_upload(request):
    """종목 파일 업로드 리포트 API"""
    from .models import Info, StockUploadedReport

    stock_code = request.POST.get('stock_code', '').strip()
    uploaded_file = request.FILES.get('file')

    if not stock_code:
        return JsonResponse({'error': '종목 코드가 필요합니다.'}, status=400)

    if not uploaded_file:
        return JsonResponse({'error': '파일을 선택해주세요.'}, status=400)

    stock = get_object_or_404(Info, code=stock_code)

    report = StockUploadedReport.objects.create(
        stock=stock,
        file=uploaded_file,
        original_filename=uploaded_file.name,
    )

    return JsonResponse({
        'success': True,
        'id': report.id,
        'original_filename': report.original_filename,
        'file_url': report.file.url,
        'created_at': report.created_at.strftime('%Y-%m-%d %H:%M'),
    })


@require_POST
def stock_uploaded_report_delete(request, report_id):
    """종목 파일 업로드 리포트 삭제 API"""
    from .models import StockUploadedReport

    report = get_object_or_404(StockUploadedReport, id=report_id)

    # 파일도 함께 삭제
    if report.file:
        report.file.delete(save=False)

    report.delete()

    return JsonResponse({'success': True})


@require_POST
def stock_uploaded_report_summary(request, report_id):
    """종목 파일 업로드 리포트 요약 저장 API"""
    from .models import StockUploadedReport

    summary = request.POST.get('summary', '')

    try:
        report = StockUploadedReport.objects.get(id=report_id)
        report.summary = summary
        report.save()
        return JsonResponse({'success': True})
    except StockUploadedReport.DoesNotExist:
        return JsonResponse({'success': False, 'error': '리포트를 찾을 수 없습니다.'})


@require_POST
def stock_uploaded_report_title(request, report_id):
    """종목 파일 업로드 리포트 제목 저장 API"""
    from .models import StockUploadedReport

    title = request.POST.get('title', '')

    try:
        report = StockUploadedReport.objects.get(id=report_id)
        report.title = title
        report.save()
        return JsonResponse({'success': True})
    except StockUploadedReport.DoesNotExist:
        return JsonResponse({'success': False, 'error': '리포트를 찾을 수 없습니다.'})


# ============ 파일 업로드 리포트 (섹터) ============

@require_POST
def sector_uploaded_report_upload(request):
    """섹터 파일 업로드 리포트 API"""
    from .models import CustomSector, SectorUploadedReport

    sector_id = request.POST.get('sector_id', '').strip()
    uploaded_file = request.FILES.get('file')

    if not sector_id:
        return JsonResponse({'error': '섹터 ID가 필요합니다.'}, status=400)

    if not uploaded_file:
        return JsonResponse({'error': '파일을 선택해주세요.'}, status=400)

    sector = get_object_or_404(CustomSector, id=sector_id)

    report = SectorUploadedReport.objects.create(
        sector=sector,
        file=uploaded_file,
        original_filename=uploaded_file.name,
    )

    return JsonResponse({
        'success': True,
        'id': report.id,
        'original_filename': report.original_filename,
        'file_url': report.file.url,
        'created_at': report.created_at.strftime('%Y-%m-%d %H:%M'),
    })


@require_POST
def sector_uploaded_report_delete(request, report_id):
    """섹터 파일 업로드 리포트 삭제 API"""
    from .models import SectorUploadedReport

    report = get_object_or_404(SectorUploadedReport, id=report_id)

    # 파일도 함께 삭제
    if report.file:
        report.file.delete(save=False)

    report.delete()

    return JsonResponse({'success': True})


@require_POST
def sector_uploaded_report_summary(request, report_id):
    """섹터 파일 업로드 리포트 요약 저장 API"""
    from .models import SectorUploadedReport

    summary = request.POST.get('summary', '')

    try:
        report = SectorUploadedReport.objects.get(id=report_id)
        report.summary = summary
        report.save()
        return JsonResponse({'success': True})
    except SectorUploadedReport.DoesNotExist:
        return JsonResponse({'success': False, 'error': '리포트를 찾을 수 없습니다.'})


@require_POST
def sector_uploaded_report_title(request, report_id):
    """섹터 파일 업로드 리포트 제목 저장 API"""
    from .models import SectorUploadedReport

    title = request.POST.get('title', '')

    try:
        report = SectorUploadedReport.objects.get(id=report_id)
        report.title = title
        report.save()
        return JsonResponse({'success': True})
    except SectorUploadedReport.DoesNotExist:
        return JsonResponse({'success': False, 'error': '리포트를 찾을 수 없습니다.'})


def refresh_stock_chart(request, code):
    """종목 차트 재수집 API (일봉/주봉/월봉 삭제 후 전체 재수집)"""
    import requests as http_requests
    import time
    from datetime import datetime, timedelta
    from .models import Info, DailyChart, WeeklyChart, MonthlyChart
    from .utils import get_valid_token

    try:
        stock = Info.objects.get(code=code)
    except Info.DoesNotExist:
        return JsonResponse({'error': '종목을 찾을 수 없습니다.'}, status=404)

    token = get_valid_token()
    if not token:
        return JsonResponse({'error': '토큰 발급 실패. 키움 API 설정을 확인하세요.'}, status=400)

    host = 'https://api.kiwoom.com'
    endpoint = '/api/dostk/chart'
    url = host + endpoint
    today = datetime.now().strftime('%Y%m%d')

    def parse_number(value):
        if not value:
            return 0
        cleaned = str(value).strip().replace(',', '')
        if cleaned.startswith('+'):
            cleaned = cleaned[1:]
        try:
            return int(cleaned)
        except (ValueError, TypeError):
            return 0

    def find_data_key(response_data):
        for key in ['stk_dt_pole_chart_qry', 'stk_daly_chart', 'stk_wk_pole_chart',
                     'stk_mon_pole_chart', 'chart', 'data', 'result', 'output']:
            if key in response_data and isinstance(response_data[key], list):
                return key
        return None

    def fetch_chart(api_id, cutoff_days):
        cutoff_date = (datetime.now() - timedelta(days=cutoff_days)).strftime('%Y%m%d')
        all_data = []
        cont_yn = 'N'
        next_key = ''

        while True:
            headers = {
                'Content-Type': 'application/json;charset=UTF-8',
                'authorization': f'Bearer {token}',
                'cont-yn': cont_yn,
                'next-key': next_key,
                'api-id': api_id,
            }
            params = {
                'stk_cd': code,
                'base_dt': today,
                'upd_stkpc_tp': '1',
            }

            try:
                resp = http_requests.post(url, headers=headers, json=params)
                if resp.status_code != 200:
                    break
                resp_data = resp.json()
                resp_data['_headers'] = {
                    k: resp.headers.get(k)
                    for k in ['next-key', 'cont-yn', 'api-id']
                }
            except Exception:
                break

            data_key = find_data_key(resp_data)
            if data_key:
                batch = resp_data[data_key]
                filtered = [item for item in batch if item.get('dt', '') >= cutoff_date]
                all_data.extend(filtered)

                if batch:
                    old_dates = [item.get('dt', '') for item in batch if item.get('dt')]
                    if old_dates and min(old_dates) < cutoff_date:
                        break

            header_info = resp_data.get('_headers', {})
            if header_info.get('cont-yn') == 'Y' and header_info.get('next-key'):
                cont_yn = 'Y'
                next_key = header_info.get('next-key')
            else:
                break

        return all_data

    def save_chart_data(ChartModel, data_list):
        created = 0
        updated = 0
        for item in data_list:
            try:
                date = datetime.strptime(item['dt'], '%Y%m%d').date()
                _, is_created = ChartModel.objects.update_or_create(
                    stock=stock,
                    date=date,
                    defaults={
                        'opening_price': parse_number(item.get('open_pric')),
                        'high_price': parse_number(item.get('high_pric')),
                        'low_price': parse_number(item.get('low_pric')),
                        'closing_price': parse_number(item.get('cur_prc')),
                        'price_change': parse_number(item.get('pred_pre')),
                        'trading_volume': parse_number(item.get('trde_qty')),
                        'trading_value': parse_number(item.get('trde_prica')),
                    }
                )
                if is_created:
                    created += 1
                else:
                    updated += 1
            except Exception:
                pass
        return created, updated

    results = {}

    # 기존 데이터 삭제
    DailyChart.objects.filter(stock=stock).delete()
    WeeklyChart.objects.filter(stock=stock).delete()
    MonthlyChart.objects.filter(stock=stock).delete()

    # 일봉 (ka10081, 2년)
    daily_data = fetch_chart('ka10081', 730)
    d_new, d_upd = save_chart_data(DailyChart, daily_data)
    results['daily'] = f'신규 {d_new}'
    time.sleep(0.1)

    # 주봉 (ka10082, 4년)
    weekly_data = fetch_chart('ka10082', 1460)
    w_new, w_upd = save_chart_data(WeeklyChart, weekly_data)
    results['weekly'] = f'신규 {w_new}'
    time.sleep(0.1)

    # 월봉 (ka10083, 6년)
    monthly_data = fetch_chart('ka10083', 2190)
    m_new, m_upd = save_chart_data(MonthlyChart, monthly_data)
    results['monthly'] = f'신규 {m_new}'

    return JsonResponse({
        'success': True,
        'message': f'일봉({results["daily"]}), 주봉({results["weekly"]}), 월봉({results["monthly"]})',
    })


def refresh_etf_chart(request, code):
    """ETF 차트 재수집 API (일봉/주봉/월봉 삭제 후 전체 재수집)"""
    import requests as http_requests
    import json as json_module
    from datetime import datetime, timedelta
    from .models import InfoETF, DailyChartETF, WeeklyChartETF, MonthlyChartETF

    try:
        etf = InfoETF.objects.get(code=code)
    except InfoETF.DoesNotExist:
        return JsonResponse({'error': 'ETF를 찾을 수 없습니다.'}, status=404)

    def fetch_naver_chart(timeframe, cutoff_days):
        today = datetime.now()
        start_date = today - timedelta(days=cutoff_days)
        url = 'https://api.finance.naver.com/siseJson.naver'
        params = {
            'symbol': code,
            'requestType': '1',
            'startTime': start_date.strftime('%Y%m%d'),
            'endTime': today.strftime('%Y%m%d'),
            'timeframe': timeframe,
        }
        headers = {'User-Agent': 'Mozilla/5.0'}

        try:
            resp = http_requests.get(url, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            text = resp.text.strip().replace("'", '"').replace('\n', '').replace('\t', '').replace(',]', ']')
            data = json_module.loads(text)
            return data[1:] if data and len(data) >= 2 else []
        except Exception:
            return []

    def save_etf_data(ChartModel, chart_data):
        created = 0
        updated = 0
        for row in chart_data:
            if len(row) < 6:
                continue
            try:
                date = datetime.strptime(str(row[0]), '%Y%m%d').date()
                _, is_created = ChartModel.objects.update_or_create(
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
                if is_created:
                    created += 1
                else:
                    updated += 1
            except Exception:
                pass
        return created, updated

    # 기존 데이터 삭제
    DailyChartETF.objects.filter(etf=etf).delete()
    WeeklyChartETF.objects.filter(etf=etf).delete()
    MonthlyChartETF.objects.filter(etf=etf).delete()

    # 일봉 (2년), 주봉 (4년), 월봉 (6년)
    d_data = fetch_naver_chart('day', 730)
    d_new, _ = save_etf_data(DailyChartETF, d_data)

    w_data = fetch_naver_chart('week', 1460)
    w_new, _ = save_etf_data(WeeklyChartETF, w_data)

    m_data = fetch_naver_chart('month', 2190)
    m_new, _ = save_etf_data(MonthlyChartETF, m_data)

    return JsonResponse({
        'success': True,
        'message': f'일봉(신규 {d_new}), 주봉(신규 {w_new}), 월봉(신규 {m_new})',
    })
