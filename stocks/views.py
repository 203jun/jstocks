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
from . import gongsi_signal, stock_signal
from .models import Holding, Info, Financial, DailyChart, WeeklyChart, MonthlyChart, Report, Gongsi, IndexChart, MarketTrend, AiNote, InvestorTrend, ShortSelling, MarketDiary
from .ai_note import build_note_panel
from .market_signal import build_market_panel, build_prompt_vars
from .prompts import (
    GONGSI_ALL_PROMPT_DEFAULT, GONGSI_ALL_PROMPT_KEY,
    REPORT_PROMPT_DEFAULT, REPORT_PROMPT_KEY,
    GONGSI_PROMPT_DEFAULT, GONGSI_PROMPT_KEY,
    MARKET_SIGNAL_DEFAULT, MARKET_SIGNAL_KEYS, MARKET_SIGNAL_VARIABLES,
    SUPPLY_PROMPT_DEFAULT, SUPPLY_PROMPT_KEY, get_prompt,
)
from .gongsi_prompt import (
    GONGSI_ALL_VARIABLES, GONGSI_VARIABLES,
    build_gongsi_all_prompt_vars, build_gongsi_prompt_vars, gongsi_body_targets,
)
from .gongsi_signal import classify as _classify_gongsi
from .report_prompt import REPORT_VARIABLES, build_report_prompt_vars
from .report_signal import build_target_panel, gap_band
from .supply_signal import (
    FLOW_LONG_DAYS, FLOW_SHORT_DAYS, flow_band, short_z_band, turn,
)
from .supply_prompt import SUPPLY_VARIABLES, build_supply_prompt_vars

import unicodedata
import re as _re


def index(request):
    """종목 대시보드 (관심종목)"""
    from django.db.models import Max, Q

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

    normal_stocks = sort_by_theme(base_qs.filter(interest_level='normal'))
    waiting_stocks = sort_by_theme(base_qs.filter(interest_level='waiting'))

    # 보유는 고르는 값이 아니라 자산에서 정해지는 사실이다. 매일 계좌를 받아
    # Holding 을 통째로 갈아끼우므로 여기서 파생시키면 사고팔 때 저절로 따라온다.
    holding_codes = set(
        Holding.objects.filter(info__isnull=False).values_list('info__code', flat=True)
    )

    def level_of(stock):
        """화면 분류는 하나만 — 보유가 관심/대기보다 앞선다"""
        return 'holding' if stock.code in holding_codes else stock.interest_level

    # ============ 대시보드 카드 ============
    # 보유 중이면 관심 등록을 안 했어도 현황에 들어와야 한다
    target_stocks = sort_by_theme(
        base_qs.filter(
            Q(interest_level__in=['normal', 'waiting']) | Q(code__in=holding_codes)
        )
    )

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
            status_stocks.append({'stock': stock, 'level': level_of(stock), 'vol_high_20': False, 'vol_high_60': False, 'ma_align': '', 'pullback': None, 'pullback_label': '', 'has_report': False, 'inst_label': '', 'frgn_label': '', 'gongsi_cat': _gc[0] if _gc else '', 'gongsi_title': _gc[1] if _gc else '', 'has_alert': False, 'alert_conditions': '', 'recent_perf': _recent_perf_map.get(stock.code, '')})
            continue

        today = daily_data[0]
        today_vol = today.trading_volume or 0

        max_vol_20 = max((d.trading_volume or 0) for d in daily_data[:20]) if len(daily_data) >= 2 else 0
        max_vol_60 = max((d.trading_volume or 0) for d in daily_data[:60]) if len(daily_data) >= 2 else 0

        # 배열 판단
        # 이평 배열과 눌림목 — 종목 상세도 같은 계산을 쓴다 (stock_signal)
        ma_align = stock_signal.ma_alignment(daily_data)
        pullback, pullback_label = stock_signal.pullback(daily_data, ma_align)

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

        # 기관/외국인 연속 매수
        inv_data = list(InvestorTrend.objects.filter(stock=stock).order_by('-date')[:20])
        inst_label, frgn_label = stock_signal.investor_streaks(inv_data)

        # 리포트(3거래일) 최근 자료 확인
        from datetime import timedelta
        today_date = today.date
        recent_reports = list(Report.objects.filter(stock=stock, date__gte=today_date - timedelta(days=5)).order_by('-date')[:3])
        has_report = bool(recent_reports)

        report_gap = stock_signal.report_gap(stock)

        _gc = _gongsi_map.get(stock.code)
        status_stocks.append({
            'stock': stock,
            'level': level_of(stock),
            'vol_high_20': today_vol > 0 and today_vol >= max_vol_20,
            'vol_high_60': today_vol > 0 and today_vol >= max_vol_60,
            'is_bullish': today.closing_price >= today.opening_price if today.opening_price else True,
            'ma_align': ma_align,
            'pullback': pullback,
            'pullback_label': pullback_label,
            'has_report': has_report,
            'report_gap': report_gap,
            'signal_info': signal_info,
            'sparkline': sparkline,
            'inst_label': inst_label,
            'frgn_label': frgn_label,
            'gongsi_cat': _gc[0] if _gc else '',
            'gongsi_title': _gc[1] if _gc else '',
            'recent_reports': recent_reports,
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
        status_stocks[-1]['has_alert'] = bool(_alerts)
        status_stocks[-1]['alert_conditions'] = ' / '.join(_alerts)
        status_stocks[-1]['recent_perf'] = _recent_perf_map.get(stock.code, '')

    # 종목 행에도 링크를 실어 둔다 (ETF 와 같은 표에서 같은 방식으로 쓰기 위해)
    for _row in status_stocks:
        _row['is_etf'] = False
        _row['detail_url'] = f"/stocks/{_row['stock'].code}/"

    # ============ ETF 행 ============
    # 매매하는 입장에서 ETF 도 종목 하나다. 같은 표에 같은 규칙으로 올린다.
    # 수급·공시·리포트는 ETF 에 없으므로 빈 칸으로 둔다.
    from .models import InfoETF, DailyChartETF

    etf_holding_codes = set(
        Holding.objects.filter(info_etf__isnull=False).values_list('info_etf__code', flat=True)
    )
    etf_targets = list(
        InfoETF.objects.filter(is_active=True)
        .filter(Q(interest_level__isnull=False) | Q(code__in=etf_holding_codes))
        .order_by('name')
    )
    for etf_item in etf_targets:
        daily = list(DailyChartETF.objects.filter(etf=etf_item).order_by('-date')[:130])
        row = {
            'stock': etf_item,
            'is_etf': True,
            'detail_url': f'/etf/{etf_item.code}/',
            'level': 'holding' if etf_item.code in etf_holding_codes else etf_item.interest_level,
            'ma_align': '', 'pullback': None, 'pullback_label': '',
            'vol_high_20': False, 'vol_high_60': False, 'is_bullish': True,
            'signal_info': None, 'inst_label': '', 'frgn_label': '',
            'gongsi_cat': '', 'gongsi_title': '',
            'has_report': False, 'report_gap': None,
            'sparkline': [], 'has_alert': False, 'alert_conditions': '', 'recent_perf': '',
        }
        if daily:
            today_d = daily[0]
            today_vol = today_d.trading_volume or 0
            row['vol_high_20'] = today_vol > 0 and today_vol >= max((d.trading_volume or 0) for d in daily[:20])
            row['vol_high_60'] = today_vol > 0 and today_vol >= max((d.trading_volume or 0) for d in daily[:60])
            row['is_bullish'] = today_d.closing_price >= today_d.opening_price if today_d.opening_price else True
            row['sparkline'] = [d.closing_price for d in daily[:10]][::-1]

            if len(daily) >= 125:
                ma5 = sum(d.closing_price for d in daily[:5]) / 5
                ma20 = sum(d.closing_price for d in daily[:20]) / 20
                ma60 = sum(d.closing_price for d in daily[:60]) / 60
                ma120 = sum(d.closing_price for d in daily[:120]) / 120
                ma120_prev = sum(d.closing_price for d in daily[5:125]) / 120
                m = 1.005
                if ma5 > ma20 * m and ma20 > ma60 * m and ma60 > ma120 * m and ma120 > ma120_prev:
                    row['ma_align'] = 'bull'
                elif ma5 * m < ma20 and ma20 * m < ma60 and ma60 * m < ma120 and ma120 < ma120_prev:
                    row['ma_align'] = 'bear'
                else:
                    row['ma_align'] = 'mixed'

            if row['ma_align'] == 'bull' and len(daily) >= 20:
                _ma20 = sum(d.closing_price for d in daily[:20]) / 20
                gap = round((today_d.closing_price - _ma20) / _ma20 * 100, 1)
                row['pullback'] = gap
                row['pullback_label'] = ('과열' if gap > 5 else '추세중' if gap > 2
                                         else '얕은눌림' if gap > -2 else '깊은눌림' if gap > -5 else '이탈')
        status_stocks.append(row)

    from .models import SystemSetting
    prompt_status = SystemSetting.objects.filter(key='prompt_status').values_list('value', flat=True).first() or ''

    # 현황 데이터 블록 텍스트 생성 (레벨별)
    status_blocks_by_level = {'holding': [], 'normal': [], 'waiting': []}
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
        'normal_stocks': normal_stocks,
        'waiting_stocks': waiting_stocks,
        'card_a_stocks': card_a_stocks,
        'card_a_down_stocks': card_a_down_stocks,
        'card_b_stocks': card_b_stocks,
        'card_b_down_stocks': card_b_down_stocks,
        'card_d_stocks': card_d_stocks,
        'card_c_stocks': card_c_stocks,
        'card_report_stocks': card_report_stocks,
        'status_stocks': status_stocks,
        'prompt_status': prompt_status,
        'status_data_by_level': status_data_by_level,
    }
    return render(request, 'stocks/index.html', context)


# 목록에 한 번에 보여줄 종목 수. 눈으로 훑는 자리라 오십이면 충분하고,
# 더 봐야 하면 검색어를 좁히는 편이 빠르다. 예전에는 500개를 그렸다.
LIST_LIMIT = 50


def stock_list(request):
    """종목·ETF 검색 페이지"""
    # 검색어
    query = request.GET.get('q', '')
    # 시장 필터
    market = request.GET.get('market', '')
    # 정렬
    sort = request.GET.get('sort', '-market_cap')

    from django.db.models import Q as _Q
    from .models import InfoETF

    stocks = Info.objects.filter(is_active=True)
    if query:
        stocks = stocks.filter(_Q(name__icontains=query) | _Q(code__icontains=query))
    if market:
        stocks = stocks.filter(market=market)
    total = stocks.count()
    # 눈으로 훑는 목록이라 오십이면 충분하다. 더 보려면 검색어를 좁힌다.
    stocks = stocks.order_by(sort)[:LIST_LIMIT]

    # ETF 는 검색창을 따로 둔다. 시장(코스피/코스닥)·정렬이 종목에만 걸리고
    # ETF 에는 뜻이 없어서, 한 창을 같이 쓰면 한쪽을 찾을 때 다른 쪽이
    # 조건에 걸려 사라진다.
    etf_query = request.GET.get('etf_q', '').strip()
    etfs = InfoETF.objects.filter(is_active=True)
    if etf_query:
        etfs = etfs.filter(_Q(name__icontains=etf_query) | _Q(code__icontains=etf_query))
    etfs = list(etfs.order_by('-market_cap'))

    # 보유 표시는 자산에서 가져온다 (수동 플래그는 실제와 어긋나기 쉽다)
    _held = Holding.objects.all()
    holding_codes = set(_held.filter(info__isnull=False).values_list('info__code', flat=True))
    etf_holding_codes = set(_held.filter(info_etf__isnull=False).values_list('info_etf__code', flat=True))

    context = {
        'stocks': stocks,
        'stock_total': total,
        'list_limit': LIST_LIMIT,
        'etfs': etfs,
        'etf_query': etf_query,
        'query': query,
        'market': market,
        'sort': sort,
        'holding_codes': holding_codes,
        'etf_holding_codes': etf_holding_codes,
    }
    return render(request, 'stocks/stock_list.html', context)


def stock_detail(request, code):
    """종목 상세 페이지"""
    from django.db.models import Q
    stock = get_object_or_404(Info.objects.prefetch_related('themes__category'), code=code)
    # 보유는 자산에서 판정한다 (Info.is_holding 수동 플래그는 더 이상 쓰지 않는다)
    is_holding = Holding.objects.filter(info=stock).exists()

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

    # 일봉 차트 데이터 (표시 240일 + 120일선 계산용 120일 + 여유 = 420일)
    daily_charts = list(DailyChart.objects.filter(
        stock=stock
    ).order_by('-date')[:420])
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

    # 화면 최대 범위(240일) + 120일선 계산분(120일)을 내려보낸다
    daily_charts = daily_charts[-360:]
    ma20 = ma20[-360:]
    ma60 = ma60[-360:]

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
    # 표시 104주 + 60주선 계산용 60주
    weekly_charts = list(WeeklyChart.objects.filter(
        stock=stock
    ).order_by('-date')[:164])
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

    # 월봉 차트 데이터 (표시 72개월 + 12개월선 계산용 12개월)
    monthly_charts = list(MonthlyChart.objects.filter(
        stock=stock
    ).order_by('-date')[:84])
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

# 리포트 — 화면에는 최근 20건, 프롬프트는 180일치를 훑는다.
    # 한 번에 넉넉히 읽어 두 곳이 나눠 쓴다.
    reports_queryset = Report.objects.filter(stock=stock).order_by('-date')
    total_reports = reports_queryset.count()
    reports_all = list(reports_queryset[:120])
    reports = reports_all[:20]

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
            r.gap_band = gap_band(r.gap_rate)

    # 공시 — 화면에는 최근 20건, 탭 프롬프트는 180일치를 훑는다.
    # 한 번에 넉넉히 읽어 두 곳이 나눠 쓴다.
    gongsi_window = list(Gongsi.objects.filter(stock=stock).order_by('-date')[:200])
    for g in gongsi_window:
        g.cat = _classify_gongsi(g.title)
    gongsi_list = gongsi_window[:20]

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

        # 외국인/기관 — 순매수 '주식 수'를 지분율로 바꿔 본다.
        #
        # 주식 수를 그대로 보여주면 종목 크기에 따라 뜻이 달라진다. 10만 주는
        # 삼성전자엔 티끌이고 소형주엔 사건이다. 상장주식수로 나눠야 종목끼리
        # 견줄 수 있다. listed_shares 는 천주 단위다(시총/주식수 = 주가×1000).
        #
        # 60일과 20일을 같이 본다. 둘의 상관이 0.7 이라 겹치긴 하지만 부호가
        # 엇갈리는 경우가 네 번에 한 번이고, 그 엇갈림이 가장 큰 신호다 —
        # '석 달 팔다가 최근 한 달 사는 중'이 이후 20거래일 +14.9% 로 가장
        # 좋았고, 그 반대가 +4.3% 로 가장 나빴다(외국인 기준, 표본 2,165).
        shares = (stock.listed_shares or 0) * 1000
        w60 = min(FLOW_LONG_DAYS, daum_count)
        w20 = min(FLOW_SHORT_DAYS, daum_count)

        def _flow(field, days):
            """(지분율 %, 금액 억원). 금액은 그날 종가로 곱해 더한다."""
            rows = trends_asc[-days:]
            volume = sum(getattr(t, field) or 0 for t in rows)
            amount = 0
            for t in rows:
                dc = daily_charts_map.get(t.date)
                if dc and dc.closing_price:
                    amount += (getattr(t, field) or 0) * dc.closing_price
            pct = round(volume / shares * 100, 2) if shares else None
            return pct, round(amount / 100000000)

        foreign_pct, foreign_amt = _flow('daum_foreign', w60)
        foreign_pct20, foreign_amt20 = _flow('daum_foreign', w20)
        inst_pct, inst_amt = _flow('daum_institution', w60)
        inst_pct20, inst_amt20 = _flow('daum_institution', w20)

        # 공매도 비중
        short_weights = [float(s.trading_weight or 0) for s in shorts_asc[-window:]]
        short_avg = statistics.mean(short_weights) if short_weights else 0
        short_std = statistics.stdev(short_weights) if len(short_weights) > 1 else 1
        today_short_weight = short_weights[-1] if short_weights else 0
        z_score = round((today_short_weight - short_avg) / short_std, 2) if short_std > 0 else 0

        supply_dashboard = {
            'window60': w60,
            'window20': w20,
            'foreign_pct': foreign_pct,
            'foreign_amt': foreign_amt,
            'foreign_pct20': foreign_pct20,
            'foreign_band': flow_band(foreign_pct),
            'foreign_turn': turn(foreign_pct, foreign_pct20),
            'inst_pct': inst_pct,
            'inst_amt': inst_amt,
            'inst_pct20': inst_pct20,
            'inst_band': flow_band(inst_pct),
            'inst_turn': turn(inst_pct, inst_pct20),
            'short_weight': round(today_short_weight, 1),
            'z_score': z_score,
            'z_band': short_z_band(z_score),
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

    # 저장된 자료 (최신순)
    from .models import Material
    materials = list(Material.objects.filter(stock=stock))

    # 저장된 텔레그램 메시지 (최신순)
    from .models import TelegramMessage
    telegram_messages = TelegramMessage.objects.filter(stock=stock).order_by('-date', '-time')

    # 뉴스 프롬프트용 변수. 핵심브리핑·이벤트는 리서치 칸에서 읽는다.
    from datetime import date as _date
    from django.db.models import Q as _Q
    _today = _date.today()
    future_events_text = research_text(stock, '이벤트') or research_text(stock, '향후 이벤트')
    news_prompt_vars = {
        'stock_name': stock.name,
        'stock_code': stock.code,
        'sector_name': '',
        'key_briefing': research_text(stock, '핵심브리핑'),
        'financial_analysis': stock.financial_analysis_v2 or '',
        'consensus_analysis': stock.consensus_analysis or '',
        'future_events': future_events_text,
    }

    # 질문리포트
    from .models import StockQuestionReport, ResearchPrompt, QuickReport, SummaryReport
    question_reports = list(StockQuestionReport.objects.filter(stock=stock).order_by('-created_at'))

    # 리서치는 '프롬프트 칸'이다. 등록된 프롬프트가 곧 칸이고, 저장된
    # 리서치가 그 칸을 채운다. 어느 칸을 안 채웠는지가 보여야 해서
    # 빈 칸도 같이 그린다 (research_slots 참고).
    #
    # 순서는 설정 화면의 프롬프트 순서(order 필드)를 그대로 따른다.
    # 예전에는 여기에 순서 배열 세 개를 손으로 박아 두고 있었는데,
    # 프롬프트를 더하거나 이름을 바꾸면 조용히 맨 뒤로 밀렸다.
    from . import research_slots
    research_groups, custom_question_reports, gongsi_health = research_slots.build_groups(
        stock, question_reports)

    # 전체내용 생성 (DB에 있는 모든 분석 데이터)
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
    # 그룹별 리서치 (기업분석 · 업데이트 · 정리 · 대기)
    for _g in research_groups:
        for _s in _g['slots']:
            r = _s['report']
            if r and r.report:
                all_content_sections.append(
                    f"## {_g['name']}: {r.question} ({r.updated_at.strftime('%Y-%m-%d')})\n{r.report}")
    # 일반 질문
    for r in custom_question_reports:
        if r.report:
            all_content_sections.append(f"## 일반: {r.question} ({r.updated_at.strftime('%Y-%m-%d')})\n{r.report}")
    # 핵심브리핑
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
    # 자료 (내가 다시 읽을 만하다고 저장해둔 것)
    material_parts = []
    for m in materials:
        head = f"[{m.created_at:%Y-%m-%d}] {m.head}"
        material_parts.append(f"{head}\n{m.content}" if m.content != m.head else head)
    if material_parts:
        all_content_sections.append("## 자료\n" + '\n\n'.join(material_parts))
    # 향후 이벤트
    news_prompt_vars['all_content'] = '\n\n---\n\n'.join(all_content_sections) if all_content_sections else ''

    # 업로드 리포트
    from .models import SystemSetting
    # 거래량 변동률 계산 (전일 대비)
    volume_change_rate = None
    if len(daily_charts) >= 2:
        today_volume = daily_charts[-1].trading_volume
        prev_volume = daily_charts[-2].trading_volume
        if prev_volume and prev_volume > 0:
            volume_change_rate = round((today_volume - prev_volume) / prev_volume * 100, 1)

    # 최근 변화 — 다시 봐야 할 이유가 생겼나.
    #
    # 있다/없다가 아니라 몇 건인지 센다. 리포트 한 건과 다섯 건은 무게가
    # 다른데 배지 하나로는 같아 보였다. 창은 10거래일 — 5일이면 주 하나라
    # 지난 금요일에 나온 것을 수요일에 놓친다.
    RECENT_DAYS = 10
    recent_dates = set(d.date for d in daily_charts[-RECENT_DAYS:])
    recent_report_count = sum(1 for r in reports if r.date in recent_dates)
    recent_gongsi_count = sum(1 for g in gongsi_list if g.date in recent_dates)
    recent_window_days = RECENT_DAYS

    # 지금 주가가 어디쯤인가.
    #
    # 값 하나만 보면 비싼지 싼지 알 수 없다. 52주 범위에서 몇 % 자리인지와
    # 20일선에서 얼마나 떨어졌는지가 '지금 자리'를 말해 준다. 리서치
    # 프롬프트는 이미 쓰고 있었는데 화면에는 없었다.
    price_pos = None
    if stock.current_price and len(daily_charts) >= 20:
        year = daily_charts[-250:]
        high52 = max(c.high_price for c in year if c.high_price)
        low52 = min(c.low_price for c in year if c.low_price)
        price = float(stock.current_price)
        pos = round((price - low52) / (high52 - low52) * 100) if high52 > low52 else None
        gap20 = round((price / ma20_value - 1) * 100, 1) if ma20_value else None
        price_pos = {
            'high52': high52, 'low52': low52, 'pos': pos,
            'gap20': gap20, 'days': len(year),
        }

    # 차트 신호 — 메인 현황 표와 같은 계산(stock_signal)을 쓴다.
    # 두 화면이 같은 종목을 두고 다른 말을 하면 안 된다.
    _daily_desc = list(reversed(daily_charts))
    _align = stock_signal.ma_alignment(_daily_desc)
    _gap, _pullback_label = stock_signal.pullback(_daily_desc, _align)
    _inst_streak, _frgn_streak = stock_signal.investor_streaks(
        list(InvestorTrend.objects.filter(stock=stock).order_by('-date')[:20]))
    _gongsi_recent = [g for g in gongsi_list if g.date in recent_dates]
    _gongsi_good = sum(1 for g in _gongsi_recent if gongsi_signal.classify(g.title) == '호재')
    _gongsi_bad = sum(1 for g in _gongsi_recent if gongsi_signal.classify(g.title) == '악재')
    signal_panel = {
        'align': _align,
        'align_name': stock_signal.ALIGN_NAMES.get(_align, ''),
        'pullback': _gap,
        'pullback_label': _pullback_label,
        'vol_high': stock_signal.volume_high(_daily_desc),
        'big_candle': stock_signal.big_candle(_daily_desc),
        'new_high': stock_signal.new_high(_daily_desc),
        'inst_streak': _inst_streak,
        'frgn_streak': _frgn_streak,
        'report_gap': stock_signal.report_gap(stock),
        'report_count': recent_report_count,
        'gongsi_count': recent_gongsi_count,
        'gongsi_good': _gongsi_good,
        'gongsi_bad': _gongsi_bad,
        'window': RECENT_DAYS,
    }

    # 사업보고서를 읽고 쓴 리서치가 낡았는지. 리서치 칸까지 내려가야 보이던
    # 것을 위로 올린다 — '다시 봐야 할 이유'의 대표다.
    new_report_alert = None
    if not gongsi_health:
        _newest = research_slots.latest_regular(stock)
        _oldest = min(
            (s['report'].updated_at.date()
             for g in research_groups if g['name'] == '기업분석'
             for s in g['slots'] if s['filled'] and s['auto_report']),
            default=None)
        if _newest and _oldest and _newest.date > _oldest:
            new_report_alert = {
                'title': research_slots._tidy(_newest.title),
                'date': _newest.date,
            }

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

    # 리포트 탭 '목표가' 카드. 괴리율은 여기서만 '지금' 기준으로 잰다 —
    # 표의 괴리율은 발행일 종가로 굳은 기록이라 오늘 살지 말지를 말해주지
    # 않는다. 목록·핵심브리핑도 현재가 기준이라 셈법이 서로 맞는다.
    #
    # 대상 리포트는 목록(index)과 똑같이 '목표가가 있는 가장 최근 것'으로
    # 고른다. 화면에 보이는 최근 20건 안에서 찾으면, 그 20건에 목표가가
    # 하나도 없을 때 목록과 다른 리포트를 집게 된다.
    # 공시 프롬프트 두 벌.
    #   행 단위 — 한 건 깊이. 공시별 값(제목·본문·링크)은 화면이 채운다.
    #   탭 단위 — 최근 180일을 훑는다. 목록까지 서버가 만든다.
    _charts_asc = sorted(daily_charts, key=lambda c: c.date)
    gongsi_prompt_vars = build_gongsi_prompt_vars(stock, _charts_asc, _today)
    gongsi_all_prompt_vars = build_gongsi_all_prompt_vars(
        stock, gongsi_window, _charts_asc, _today)

    target_panel = build_target_panel(stock, _today)

    # 리포트 프롬프트 — 세 탭 중 여기만 1차 자료(원문)가 없다.
    # 진짜 재료는 숫자에 있으므로(방향·갈리는 폭·괴리율) 검색이 실패해도
    # 판단이 무너지지 않는다.
    report_prompt_vars = build_report_prompt_vars(
        stock, target_panel, reports_all,
        _cons_annual[-3:][::-1] + _cons_quarter[-4:][::-1],
        sorted(daily_charts, key=lambda c: c.date), _today,
    )


    # 수급 프롬프트 입력값.
    #
    # 값은 서버에서 만든다. 화면(JS)에서 합계를 내면 계산이 갈라지고, 대시보드가
    # 이미 정규화해둔 값을 다시 만들게 된다.
    supply_prompt_vars = {}
    if supply_dashboard:
        supply_prompt_vars = build_supply_prompt_vars(
            stock, supply_dashboard, target_panel,
            trends_asc, shorts_asc, sorted(daily_charts, key=lambda c: c.date),
            reports, _today,
        )


    # 3개월 평균 목표주가 (컨센서스 프롬프트용)
    from datetime import timedelta
    three_months_ago = _today - timedelta(days=90)
    recent_target_prices = Report.objects.filter(
        stock=stock, date__gte=three_months_ago, target_price__isnull=False
    ).values_list('target_price', flat=True)
    avg_target_price_3m = round(sum(recent_target_prices) / len(recent_target_prices)) if recent_target_prices else None

    # 주가 vs 목표가 차트 (리포트 탭)
    #
    # x 축은 날짜다. 예전에는 리포트 순번을 축으로 써서, 같은 날 5건이 나오면
    # 그 하루가 화면에서 5칸을 차지하고 한 달 공백은 한 칸으로 붙었다.
    #
    # 같은 날 여러 증권사가 내는 목표가는 하루 안에서 24만원까지 갈리므로
    # 선으로 이으면 지그재그가 된다. 날짜별로 묶어 평균 하나로 찍고,
    # 최저~최고를 밴드로 둘러 이견의 폭을 함께 보여준다.
    TARGET_CHART_DAYS = 20   # 리포트 건수가 아니라 '날짜' 20개

    target_chart_data = []
    price_chart_data = []
    with_target = Report.objects.filter(
        stock=stock, target_price__isnull=False, date__isnull=False
    ).values_list('date', 'target_price')

    by_date = {}
    for d, tp in with_target:
        by_date.setdefault(d, []).append(int(tp))

    if by_date:
        dates = sorted(by_date, reverse=True)[:TARGET_CHART_DAYS]
        dates.sort()
        closes = {
            dc.date: dc.closing_price
            for dc in DailyChart.objects.filter(stock=stock, date__gte=dates[0])
        }
        for d in dates:
            prices = by_date[d]
            avg = round(sum(prices) / len(prices))
            close = closes.get(d)
            target_chart_data.append({
                'x': d.strftime('%Y-%m-%d'),
                'avg': avg,
                'low': min(prices),
                'high': max(prices),
                'count': len(prices),
                # 휴장일 등으로 그날 종가가 없을 수 있다. 목표가는 유효하므로
                # 점은 찍고 괴리율만 비운다.
                'close': close,
                'gap': round((avg - close) / close * 100, 1) if close else None,
            })
        # 주가선은 리포트가 있는 날만이 아니라 일봉 전체로 그린다
        price_chart_data = [
            {'x': d.strftime('%Y-%m-%d'), 'y': c}
            for d, c in sorted(closes.items())
        ]

    # 키움 ka01690 보유 현황 (Holding) + 어제 대비 diff 계산
    # 보조 계좌는 자산 페이지 전용이므로 여기서는 주계좌 보유분만 본다
    holding = stock.holding_record.filter(account__is_primary=True).first()
    if holding:
        # 원금 = 평가금액 - 평가손익
        if holding.eval_amount is not None and holding.eval_profit is not None:
            holding.principal = holding.eval_amount - holding.eval_profit
        else:
            holding.principal = None

        # 어제 대비: 이전 거래일 종가 기준으로 평가금액/평가손익/수익률만 재계산
        holding.diff_eval_amount = None
        holding.diff_eval_profit = None
        holding.diff_profit_rate = None
        from datetime import date as _date
        prev_chart = DailyChart.objects.filter(
            stock=stock, date__lt=_date.today()
        ).order_by('-date').first()
        if prev_chart and holding.rmnd_qty and holding.buy_uv:
            prev_close = int(prev_chart.closing_price)
            qty = holding.rmnd_qty
            buy_uv = holding.buy_uv
            y_eval_amount = prev_close * qty
            y_eval_profit = (prev_close - buy_uv) * qty
            y_profit_rate = ((prev_close - buy_uv) / buy_uv * 100) if buy_uv else 0
            if holding.eval_amount is not None:
                holding.diff_eval_amount = holding.eval_amount - y_eval_amount
            if holding.eval_profit is not None:
                holding.diff_eval_profit = holding.eval_profit - y_eval_profit
            if holding.profit_rate is not None:
                holding.diff_profit_rate = round(float(holding.profit_rate) - y_profit_rate, 2)

    context = {
        'stock': stock,
        'is_holding': is_holding,
        'holding': holding,
        'sectors': sectors,
        'volume_change_rate': volume_change_rate,
        'recent_report_count': recent_report_count,
        'recent_gongsi_count': recent_gongsi_count,
        'recent_window_days': recent_window_days,
        'price_pos': price_pos,
        'signal_panel': signal_panel,
        'new_report_alert': new_report_alert,
        'latest_investor': latest_investor,
        'latest_short': latest_short,
        'target_panel': target_panel,
        # 변수 목록도 같은 덩어리에 실어 보낸다. 따로 |safe 로 뿌리면 파이썬
        # 튜플 표기가 그대로 나가고, JS 는 ('a','b') 를 쉼표 연산자로 읽어
        # 빈 문자열로 만들어 버린다.
        'report_prompt': {
            'key': REPORT_PROMPT_KEY,
            'template': get_prompt(REPORT_PROMPT_KEY, REPORT_PROMPT_DEFAULT),
            'vars': report_prompt_vars,
            'help': REPORT_VARIABLES,
        },
        'gongsi_all_prompt': {
            'key': GONGSI_ALL_PROMPT_KEY,
            'template': get_prompt(GONGSI_ALL_PROMPT_KEY, GONGSI_ALL_PROMPT_DEFAULT),
            'vars': gongsi_all_prompt_vars,
            'help': GONGSI_ALL_VARIABLES,
            # 본문은 무거워서 미리 안 받는다. 버튼을 누를 때 화면이 받아 채운다.
            'bodies': gongsi_body_targets(gongsi_window, _today),
        },
        'gongsi_prompt': {
            'key': GONGSI_PROMPT_KEY,
            'template': get_prompt(GONGSI_PROMPT_KEY, GONGSI_PROMPT_DEFAULT),
            'vars': gongsi_prompt_vars,
            'help': GONGSI_VARIABLES,
        },
        'supply_prompt': {
            'key': SUPPLY_PROMPT_KEY,
            'template': get_prompt(SUPPLY_PROMPT_KEY, SUPPLY_PROMPT_DEFAULT),
            'vars': supply_prompt_vars,
            'help': SUPPLY_VARIABLES,
        },
        # AI 판단 — 리포트·수급·공시가 시황과 같은 조각을 쓴다
        'report_note': build_note_panel('report', stock.code),
        'supply_note': build_note_panel('supply', stock.code),
        'gongsi_note': build_note_panel('gongsi', stock.code),
        'analysis_stances': AiNote.STANCES,
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
        'materials': materials,
        'telegram_messages': telegram_messages,
        'question_reports': question_reports,
        'research_groups': research_groups,
        'research_filled': sum(g['filled'] for g in research_groups) + len(custom_question_reports),
        'research_health': gongsi_health,
        'custom_question_reports': custom_question_reports,
        'price_chart_data': json.dumps(price_chart_data),
        'target_chart_data': json.dumps(target_chart_data),
        'saved_prompts': {s.key: s.value for s in SystemSetting.objects.filter(key__startswith='prompt_')},
        'news_prompt_vars': news_prompt_vars,
        'ma10_value': ma10_value,
        'ma20_value': ma20_value,
        'ma60_value': ma60_value,
        'avg_target_price_3m': avg_target_price_3m,
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
                logger.info(f'[FAV] {stock_code} save_investor_daum 시작')
                call_command('save_investor_daum', code=stock_code, mode='all')
                logger.info(f'[FAV] {stock_code} save_short_selling 시작')
                call_command('save_short_selling', code=stock_code, mode='all')
                logger.info(f'[FAV] {stock_code} save_gongsi_stock 시작')
                call_command('save_gongsi_stock', code=stock_code)
                logger.info(f'[FAV] {stock_code} save_fnguide_report 시작')
                call_command('save_fnguide_report', code=stock_code)
            else:  # remove
                # 데이터 삭제
                call_command('save_investor_trend', clear=True, code=stock_code)
                call_command('save_short_selling', clear=True, code=stock_code)
                call_command('save_gongsi_stock', clear=True, code=stock_code)
                call_command('save_fnguide_report', clear=True, code=stock_code)
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

        # 보유 중이면 관심을 뗄 수 없다. 떼는 순간 run_fav_commands(remove) 가
        # 수급·공매도·공시·리포트를 지운다. 계좌 동기화가 다음 날 등급을 도로
        # 채우긴 하지만 그 사이 자료가 한 번 사라진다 — 돈이 들어가 있는
        # 종목에서 그럴 이유가 없다.
        if new_interest_level is None and Holding.objects.filter(info=stock).exists():
            messages.error(request, f'{stock.name}은(는) 보유 중이라 관심을 해제할 수 없습니다.')
            return redirect('stocks:stock_edit', code=code)

        stock.interest_level = new_interest_level
        stock.is_tracking = request.POST.get('is_tracking') == 'on'

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








SNAPSHOT_FIELDS = (
    'total_buy_amount', 'total_eval_amount', 'total_eval_profit',
    'profit_rate', 'deposit_balance', 'estimated_asset', 'cash_weight',
)


def _snapshot_to_dict(snapshot):
    """DailyAccountSnapshot을 합산 결과와 동일한 형태의 dict로 변환"""
    return {
        'date': snapshot.date,
        'total_buy_amount': snapshot.total_buy_amount,
        'total_eval_amount': snapshot.total_eval_amount,
        'total_eval_profit': snapshot.total_eval_profit,
        'profit_rate': float(snapshot.profit_rate) if snapshot.profit_rate is not None else None,
        'deposit_balance': snapshot.deposit_balance,
        'estimated_asset': snapshot.estimated_asset,
        'cash_weight': float(snapshot.cash_weight) if snapshot.cash_weight is not None else None,
    }


def _merge_snapshots(snapshots):
    """
    같은 날짜의 여러 계좌 스냅샷을 1건으로 합산한다.

    금액은 단순 합, 수익률은 평가손익/매입가로 재계산, 현금비중은
    추정자산 가중평균. 그날 데이터가 없는 계좌는 그냥 빠지므로,
    계좌를 도중에 추가하면 그 시점부터 합계가 올라간다.
    """
    merged = {f: None for f in SNAPSHOT_FIELDS}
    merged['date'] = snapshots[0].date

    for field in ('total_buy_amount', 'total_eval_amount', 'total_eval_profit',
                  'deposit_balance', 'estimated_asset'):
        values = [getattr(s, field) for s in snapshots if getattr(s, field) is not None]
        merged[field] = sum(values) if values else None

    buy = merged['total_buy_amount']
    profit = merged['total_eval_profit']
    merged['profit_rate'] = round(profit / buy * 100, 2) if buy and profit is not None else None

    weighted = [
        (float(s.cash_weight), s.estimated_asset)
        for s in snapshots
        if s.cash_weight is not None and s.estimated_asset
    ]
    total_weight = sum(w for _, w in weighted)
    if total_weight:
        merged['cash_weight'] = round(
            sum(v * w for v, w in weighted) / total_weight, 2
        )

    return merged


def _chart_point(row):
    """합산/단일 스냅샷 dict를 차트 데이터 포인트로 변환"""
    eval_amount = row['total_eval_amount'] or 0
    eval_profit = row['total_eval_profit']
    # 원금은 보유 종목 표와 같은 정의(평가금액 - 평가손익)를 쓴다.
    # 스냅샷의 total_buy_amount는 수수료 등으로 미세하게 어긋나, 그걸 쓰면
    # 차트의 두 선 간격이 평가손익과 딱 맞아떨어지지 않는다.
    principal = (eval_amount - eval_profit) if eval_profit is not None else (row['total_buy_amount'] or 0)
    return {
        'time': row['date'].strftime('%Y-%m-%d'),
        'total_eval_amount': eval_amount,
        'total_buy_amount': principal,
        'profit_rate': row['profit_rate'] if row['profit_rate'] is not None else 0,
        'total_eval_profit': row['total_eval_profit'],
        'deposit_balance': row['deposit_balance'],
        'cash_weight': row['cash_weight'],
    }


def _snapshot_changes(latest, prev):
    """직전 스냅샷 대비 증감 (금액은 절대값+%, 비율은 %p)"""
    if not latest or not prev:
        return {}

    def _delta(curr, before):
        if curr is None or before is None:
            return None
        diff = float(curr) - float(before)
        pct = (diff / float(before) * 100) if float(before) != 0 else None
        return {
            'diff': diff,
            'pct': round(pct, 2) if pct is not None else None,
        }

    return {f: _delta(latest[f], prev[f]) for f in SNAPSHOT_FIELDS}


def _holding_to_dict(h):
    """Holding을 합산 결과와 동일한 형태의 dict로 변환 (원금 = 평가금액 - 평가손익)"""
    principal = (
        h.eval_amount - h.eval_profit
        if h.eval_amount is not None and h.eval_profit is not None
        else None
    )
    return {
        'stk_cd': h.stk_cd,
        'stk_nm': h.stk_nm,
        'rmnd_qty': h.rmnd_qty,
        'buy_uv': h.buy_uv,
        'cur_prc': h.cur_prc,
        'eval_amount': h.eval_amount,
        'eval_profit': h.eval_profit,
        'principal': principal,
        'profit_rate': float(h.profit_rate) if h.profit_rate is not None else None,
        'eval_weight': float(h.eval_weight) if h.eval_weight is not None else None,
        'buy_weight': float(h.buy_weight) if h.buy_weight is not None else None,
        'is_etf': h.info_etf_id is not None,
        # Info에 연동된 종목만 상세 페이지가 있다 (미연동 ETF 등은 링크를 걸면 404)
        'has_detail': h.info_id is not None,
    }


def _decorate_holdings(holdings):
    """평가비중 내림차순 정렬 + 좌우 막대 길이(가장 큰 수익률 절대값 = 100%) 계산"""
    rows = sorted(
        holdings,
        key=lambda r: r['eval_weight'] if r['eval_weight'] is not None else 0,
        reverse=True,
    )
    max_abs = max(
        (abs(r['profit_rate']) for r in rows if r['profit_rate'] is not None),
        default=0,
    )
    for r in rows:
        rate = r['profit_rate'] or 0
        r['bar_pct'] = round(abs(rate) / max_abs * 100, 1) if max_abs else 0
        r['is_profit'] = rate > 0
        r['is_loss'] = rate < 0
    return rows


def _merge_holdings(holdings):
    """
    여러 계좌의 보유 종목을 종목코드 기준으로 합친다.

    수량·금액은 합산하고 매입단가/수익률/비중은 합산값으로 재계산한다.
    (계좌별 비중을 그대로 더하면 100%를 넘어가므로 반드시 다시 구해야 한다)
    """
    by_code = {}
    for h in holdings:
        row = by_code.get(h.stk_cd)
        if row is None:
            by_code[h.stk_cd] = {
                'stk_cd': h.stk_cd,
                'stk_nm': h.stk_nm,
                'rmnd_qty': h.rmnd_qty or 0,
                'cur_prc': h.cur_prc,
                'eval_amount': h.eval_amount or 0,
                'eval_profit': h.eval_profit or 0,
                'is_etf': h.info_etf_id is not None,
                'has_detail': h.info_id is not None,
            }
        else:
            row['rmnd_qty'] += h.rmnd_qty or 0
            row['eval_amount'] += h.eval_amount or 0
            row['eval_profit'] += h.eval_profit or 0
            if row['cur_prc'] is None:
                row['cur_prc'] = h.cur_prc
            row['is_etf'] = row['is_etf'] or h.info_etf_id is not None
            row['has_detail'] = row['has_detail'] or h.info_id is not None

    merged = list(by_code.values())
    total_eval = sum(r['eval_amount'] for r in merged)
    total_principal = sum(r['eval_amount'] - r['eval_profit'] for r in merged)

    for r in merged:
        principal = r['eval_amount'] - r['eval_profit']
        r['principal'] = principal
        r['buy_uv'] = round(principal / r['rmnd_qty']) if r['rmnd_qty'] else None
        r['profit_rate'] = round(r['eval_profit'] / principal * 100, 2) if principal else None
        r['eval_weight'] = round(r['eval_amount'] / total_eval * 100, 2) if total_eval else None
        r['buy_weight'] = round(principal / total_principal * 100, 2) if total_principal else None

    merged.sort(key=lambda r: r['eval_weight'] or 0, reverse=True)
    return merged


def asset(request):
    """자산 페이지 (계좌별/합산 총자산 시계열 + 보유 종목 + 실현손익)"""
    from .models import Account

    accounts = list(Account.objects.filter(is_active=True))

    # 계좌별 전체 스냅샷 (기간 자르기는 차트 쪽 기간 버튼이 담당)
    snapshots_by_account = {a.id: [] for a in accounts}
    for account in accounts:
        snapshots_by_account[account.id] = list(account.snapshots.order_by('date'))

    # 합산: 같은 날짜끼리 묶어서 계좌 수만큼 합침
    by_date = {}
    for rows in snapshots_by_account.values():
        for s in rows:
            by_date.setdefault(s.date, []).append(s)
    merged_rows = [_merge_snapshots(by_date[d]) for d in sorted(by_date)]

    holdings_by_account = {a.id: list(a.holdings.select_related('info', 'info_etf')) for a in accounts}
    all_holdings = [h for hs in holdings_by_account.values() for h in hs]

    def _build_tab(key, name, rows, holdings):
        latest = rows[-1] if rows else None
        prev = rows[-2] if len(rows) >= 2 else None
        return {
            'key': key,
            'name': name,
            'latest': latest,
            'changes': _snapshot_changes(latest, prev),
            'holdings': _decorate_holdings(holdings),
            'chart_data': [_chart_point(r) for r in rows],
        }

    asset_tabs = []
    if len(accounts) > 1:
        asset_tabs.append(_build_tab('all', '전체', merged_rows, _merge_holdings(all_holdings)))
    for account in accounts:
        rows = [_snapshot_to_dict(s) for s in snapshots_by_account[account.id]]
        holdings = [_holding_to_dict(h) for h in holdings_by_account[account.id]]
        asset_tabs.append(_build_tab(account.key, account.name, rows, holdings))

    chart_data_by_tab = {t['key']: t['chart_data'] for t in asset_tabs}
    active_tab = asset_tabs[0]['key'] if asset_tabs else ''

    context = {
        'asset_tabs': asset_tabs,
        'active_tab': active_tab,
        'show_tabs': len(asset_tabs) > 1,
        'chart_data_by_tab': json.dumps(chart_data_by_tab),
    }
    return render(request, 'stocks/asset.html', context)


def market(request):
    """시황 페이지"""
    from django.db.models import Max, Min

    # KOSPI 차트 데이터 (200일선 계산분 포함: 240일 표시 + 200일 = 440개 필요)
    kospi_charts = list(IndexChart.objects.filter(code='KOSPI').order_by('-date')[:460])
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
            # 색은 테마에 맞춰 차트 쪽에서 입힌다
            'up': c.closing_price >= c.opening_price,
        }
        for c in kospi_charts
    ]

    # KOSDAQ 차트 데이터 (200일선 계산분 포함: 240일 표시 + 200일 = 440개 필요)
    kosdaq_charts = list(IndexChart.objects.filter(code='KOSDAQ').order_by('-date')[:460])
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
            # 색은 테마에 맞춰 차트 쪽에서 입힌다
            'up': c.closing_price >= c.opening_price,
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

    # 지수 차트 하단에 겹쳐 그릴 매매동향 (선물은 수집만 하고 화면에는 쓰지 않는다)
    def get_raw_trend_data(market):
        # 차트 최대 범위(240일)를 덮을 만큼. 쌓인 게 모자라면 화면에 그 사실을 표시한다.
        trends = list(MarketTrend.objects.filter(market=market).order_by('-date')[:260])
        trends.reverse()  # oldest first
        return [
            {
                'date': t.date.strftime('%Y-%m-%d'),
                'foreign': t.foreign,
                'institution': t.institution,
                # 차트에는 안 쓰지만 외인 카드 팝업에서 같이 보여준다
                'individual': t.individual,
            }
            for t in trends
        ]

    kospi_raw_trends = get_raw_trend_data('KOSPI')
    kosdaq_raw_trends = get_raw_trend_data('KOSDAQ')

    kospi_panel = build_market_panel('KOSPI')
    kosdaq_panel = build_market_panel('KOSDAQ')
    kospi_analysis = build_note_panel('market', 'KOSPI')
    kosdaq_analysis = build_note_panel('market', 'KOSDAQ')

    # 카드 팝업은 JS 가 채우므로 패널에서 떼어내 JSON 으로 넘긴다
    def detail_json(panel):
        return json.dumps((panel or {}).get('details') or {})

    # AI 프롬프트 — 코스피/코스닥이 각자 따로 쓴다.
    # 저장된 것이 있으면 그것, 없으면 코드 기본값.
    today = datetime.now().date()
    market_prompts = {
        market: {
            'key': MARKET_SIGNAL_KEYS[market],
            'template': get_prompt(MARKET_SIGNAL_KEYS[market], MARKET_SIGNAL_DEFAULT),
            'vars': build_prompt_vars(market, panel, today),
        }
        for market, panel in (('KOSPI', kospi_panel), ('KOSDAQ', kosdaq_panel))
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
        'kospi_raw_trends': json.dumps(kospi_raw_trends),
        'kosdaq_raw_trends': json.dumps(kosdaq_raw_trends),
        'kospi_indicators': kospi_panel,
        'kosdaq_indicators': kosdaq_panel,
        'kospi_card_details': detail_json(kospi_panel),
        'kosdaq_card_details': detail_json(kosdaq_panel),
        'market_prompts': market_prompts,
        'market_prompt_help': MARKET_SIGNAL_VARIABLES,
        'kospi_analysis': kospi_analysis,
        'kosdaq_analysis': kosdaq_analysis,
        'analysis_stances': AiNote.STANCES,
    }
    return render(request, 'stocks/market.html', context)




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


def _parse_bool(val):
    return str(val).lower() in ('1', 'true', 'on', 'yes')












@require_GET
def fetch_stock_data_loader(request, code):
    """종목 데이터 불러오기 API (선택적 데이터 로드)"""
    import re
    from bs4 import BeautifulSoup
    from .models import Material, TelegramMessage, StockQuestionReport

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


    # 핵심 브리핑 — 이제 리서치 칸이다
    if 'key_briefing' in types:
        lines.append("## 핵심 브리핑")
        _kb = research_text(stock, '핵심브리핑')
        if _kb:
            lines.append(_kb)
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

    # 자료 (최대 10개)
    if 'material' in types:
        lines.append("## 자료 (최대 10개)")
        material_list = Material.objects.filter(stock=stock)[:10]
        if material_list:
            for m in material_list:
                lines.append(f"- {m.head}")
                if m.link:
                    lines.append(f"  링크: {m.link}")
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
    from .models import Material

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

    # 저장한 자료 (최근 5개)
    materials = Material.objects.filter(stock=stock)[:5]

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

    # 자료
    lines.append("## 자료 (최근 5개)")
    if materials:
        for m in materials:
            lines.append(f"- {m.head}")
            if m.link:
                lines.append(f"  링크: {m.link}")
    else:
        lines.append("- 없음")
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

    # 자료 (최대 10개)
    if 'material' in types:
        lines.append("## 자료 (최대 10개)")
        material_list = Material.objects.filter(stock=stock)[:10]
        if material_list:
            for m in material_list:
                lines.append(f"- {m.head}")
                if m.link:
                    lines.append(f"  링크: {m.link}")
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
    from .models import Material, TelegramMessage, StockQuestionReport, StockUploadedReport, SystemSetting

    stock = get_object_or_404(Info, code=code)

    # 저장된 데이터 타입 가져오기
    try:
        saved_types = SystemSetting.objects.get(key='briefing_data_types').value
        data_types = [t for t in saved_types.split(',') if t]  # 빈 문자열 제거
        if not data_types:
            data_types = ['analysis', 'key_briefing', 'report', 'youtube', 'news', 'telegram', 'memo']
    except SystemSetting.DoesNotExist:
        data_types = ['analysis', 'key_briefing', 'report', 'youtube', 'news', 'telegram', 'memo']

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

# 2. 핵심 브리핑 — 이제 리서치 칸이다
    if 'key_briefing' in data_types:
        lines.append("## 핵심 브리핑")
        _kb = research_text(stock, '핵심브리핑')
        if _kb:
            lines.append(_kb)
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

    # 5. 자료 (최대 10개)
    if 'material' in data_types:
        lines.append("## 자료 (최대 10개)")
        material_list = Material.objects.filter(stock=stock)[:10]
        if material_list:
            for m in material_list:
                lines.append(f"\n### {m.head}")
                if m.link:
                    lines.append(f"링크: {m.link}")
                lines.append(html_to_text(m.content))
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


# ── DART 공시 본문 ──────────────────────────────────────────────────
#
# 예전에는 OpenAPI(document.xml)로 원문 ZIP 을 받았다. 그런데 그 키가 계정의
# 개인정보 보유기간이 지나면 잠긴다(코드 901). 주기적으로 갱신해 주지 않으면
# 조용히 죽는 구조라, 실제로 죽어 있는 것을 한참 뒤에야 알았다.
#
# 그래서 사람이 보는 뷰어 페이지를 그대로 읽는다. 키도 쿠키도 Referer 도
# 필요 없다. 대신 DART 의 HTML/JS 모양에 기대므로, 못 읽으면 왜 못 읽었는지를
# 화면에 그대로 올린다.
#
#   1) dsaf001/main.do?rcpNo=...  안에 문서 좌표가 JS 로 박혀 있다
#        viewDoc("20260421900330", "11338085", "0", "0", "0", "HTML", "")
#   2) report/viewer.do?rcpNo=&dcmNo=&eleId=&offset=&length=&dtd=  가 본문
#
# 문서는 두 모양이다.
#   dtd=HTML       수시공시. 1) 의 좌표 하나로 본문이 통째로 나온다.
#   dtd=dart4.xsd  정기보고서류. 1) 은 목차뿐이고 본문은 treeData 에 절 단위로
#                  쪼개져 있어 노드마다 받아야 한다. 하위 노드는 상위에 이미
#                  들어 있으므로 최상위만 받는다.

DART_VIEWER_BASE = 'https://dart.fss.or.kr'
DART_USER_AGENT = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/126.0 Safari/537.36'
)

# 사업보고서는 최상위 노드 17개에 원문이 4MB 를 넘고, 그중 '재무에 관한 사항'
# 하나가 3.5MB 다. 상한이 없으면 그걸 다 받아 100만 자를 만든다.
#
# 넘치면 잘라서 주지 않고 아예 거절한다. 반기·사업보고서를 프롬프트로 옮겨
# 읽을 일이 없는데, 잘라 주면 앞부분만 든 채로 다 봤다고 착각하게 된다.
# 투자설명서 71,280자 · 주주총회소집공고 52,295자 는 통과하는 선이다.
DART_MAX_NODES = 30
DART_MAX_CHARS = 100_000

_DART_VIEWDOC_RE = _re.compile(
    r'viewDoc\(\s*"(\d+)"\s*,\s*"(\d+)"\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"'
    r'\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"')
# treeData 는 깊이마다 var 이름이 다르다(node1 이 최상위). 최상위 블록만 훑는다.
_DART_NODE_RE = _re.compile(
    r'var node1 = \{\};(.*?)(?=var node\d+ = \{\};|treeData\.push)', _re.S)


def _dart_node_field(block, key):
    m = _re.search(r"\['" + key + r"'\]\s*=\s*\"([^\"]*)\"", block)
    return m.group(1) if m else ''


def _dart_top_nodes(html):
    """정기보고서류의 최상위 목차 노드들. 수시공시면 빈 목록."""
    nodes = []
    for m in _DART_NODE_RE.finditer(html):
        block = m.group(1)
        if not _dart_node_field(block, 'dcmNo'):
            continue
        nodes.append({key: _dart_node_field(block, key)
                      for key in ('text', 'rcpNo', 'dcmNo', 'eleId', 'offset', 'length', 'dtd')})
    return nodes


def _dart_viewer_text(session, params):
    """viewer.do 한 조각 -> 본문 텍스트. 인코딩은 cp949 다."""
    from bs4 import BeautifulSoup

    resp = session.get(f'{DART_VIEWER_BASE}/report/viewer.do', params=params, timeout=30)
    resp.raise_for_status()
    raw = resp.content
    text = None
    for enc in ('cp949', 'euc-kr', 'utf-8'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return ''

    soup = BeautifulSoup(text, 'html.parser')
    for tag in soup(['style', 'script']):
        tag.decompose()
    body = soup.find('body') or soup
    return _tidy_dart_text(body.get_text('\n', strip=True))


# DART 는 표로 쓴다. 텍스트로 뽑으면 라벨과 값이 줄마다 흩어져
# "1. 처분예정주식(주) / 보통주식 / 9,007 / 기타주식 / -" 이 다섯 줄이 된다.
# 한 공시가 282줄이 되고 그중 238줄이 12자 이하였다. 사람도 AI 도 짝을 맞추기
# 어렵고, 실제로 '본문에 내용이 없다'는 답이 돌아왔다. 이어지는 짧은 줄을
# 한 줄로 묶는다.
DART_SHORT_LINE = 24        # 이 길이 이하면 표의 조각으로 본다
DART_JOIN_LIMIT = 220       # 묶은 줄이 이보다 길어지면 끊는다


def _tidy_dart_text(text):
    out, buf = [], []

    def flush():
        if buf:
            out.append(' · '.join(buf))
            buf.clear()

    for line in text.split('\n'):
        stripped = line.strip()
        if not stripped:
            flush()
            out.append('')
            continue
        if len(stripped) <= DART_SHORT_LINE:
            buf.append(stripped)
            if sum(len(x) + 3 for x in buf) > DART_JOIN_LIMIT:
                flush()
        else:
            flush()
            out.append(stripped)
    flush()
    return _re.sub(r'\n{3,}', '\n\n', '\n'.join(out))


@require_GET
def fetch_dart_document(request, rcept_no):
    """DART 뷰어 페이지에서 공시 본문 조회 (인증키 없이 동작한다)"""
    import requests

    session = requests.Session()
    session.headers['User-Agent'] = DART_USER_AGENT

    try:
        main = session.get(f'{DART_VIEWER_BASE}/dsaf001/main.do',
                           params={'rcpNo': rcept_no}, timeout=30)
        main.raise_for_status()
    except requests.RequestException as exc:
        return JsonResponse({'error': f'DART 접속 실패: {exc}'}, status=500)

    call = _DART_VIEWDOC_RE.search(main.text)
    if not call:
        # 문서가 없거나 DART 가 화면 구조를 바꿨거나 둘 중 하나다.
        return JsonResponse({
            'error': '이 공시에서 본문 위치를 찾지 못했습니다. '
                     '원문이 없는 공시이거나 DART 화면 구조가 바뀌었습니다.',
        }, status=404)

    rcp, dcm, ele, off, length, dtd = call.groups()
    nodes = _dart_top_nodes(main.text)
    if not nodes:
        # 수시공시 — 좌표 하나가 곧 본문이다
        nodes = [{'text': '', 'rcpNo': rcp, 'dcmNo': dcm, 'eleId': ele,
                  'offset': off, 'length': length, 'dtd': dtd}]

    too_long = len(nodes) > DART_MAX_NODES
    parts, total = [], 0
    try:
        for node in nodes[:DART_MAX_NODES]:
            text = _dart_viewer_text(session, {
                'rcpNo': node['rcpNo'] or rcp, 'dcmNo': node['dcmNo'],
                'eleId': node['eleId'], 'offset': node['offset'],
                'length': node['length'], 'dtd': node['dtd'],
            })
            if not text:
                continue
            parts.append(text)
            total += len(text)
            if total > DART_MAX_CHARS:
                # 더 받아봐야 어차피 거절한다. 여기서 멈춘다.
                too_long = True
                break
    except requests.RequestException as exc:
        return JsonResponse({'error': f'본문 조회 실패: {exc}'}, status=500)

    if too_long:
        return JsonResponse({
            'error': f'본문이 너무 깁니다 ({total:,}자 이상, 한도 {DART_MAX_CHARS:,}자). '
                     f'반기·사업보고서처럼 긴 문서는 프롬프트로 옮기지 않습니다. '
                     f'DART 원문에서 읽으세요.',
        }, status=413)

    if not parts:
        return JsonResponse({'error': '문서 내용을 추출할 수 없습니다.'}, status=404)

    content = '\n\n'.join(parts)
    return JsonResponse({
        'success': True,
        'rcept_no': rcept_no,
        'content_length': len(content),
        'content': content,
    })


@require_GET
def fetch_business_report(request, code):
    """
    사업보고서에서 절 하나(또는 여럿)만 뽑아 준다.

    기업분석 프롬프트의 {사업보고서} 자리를 채우려고 화면이 부른다. 공시 본문
    (fetch_dart_document)과 달리 보고서 전체를 받지 않는다 — 정기보고서는 목차
    절 단위로 나뉘어 있고, 필요한 것은 보통 'II. 사업의 내용' 하나다.

    ?sections=사업의 내용,이사회   지정 안 하면 II. 사업의 내용
    """
    import requests

    from . import business_report as br
    from .models import Info

    stock = Info.objects.filter(code=code).first()
    if not stock:
        return JsonResponse({'error': '종목을 찾을 수 없습니다.'}, status=404)

    raw = (request.GET.get('sections') or '').strip()
    sections = [s.strip() for s in raw.split(',') if s.strip()] or list(br.DEFAULT_SECTIONS)

    gongsi = br.latest_regular_report(stock)
    if not gongsi:
        return JsonResponse({
            'error': f'{stock.name}의 정기보고서(사업·반기·분기)를 찾지 못했습니다. '
                     f'공시 탭을 갱신하거나 DART 에서 직접 확인하세요.',
        }, status=404)

    rcept_no = gongsi.link.split('rcpNo=')[1].split('&')[0]
    session = requests.Session()
    session.headers['User-Agent'] = DART_USER_AGENT
    try:
        main = session.get(f'{DART_VIEWER_BASE}/dsaf001/main.do',
                           params={'rcpNo': rcept_no}, timeout=30)
        main.raise_for_status()
    except requests.RequestException as exc:
        return JsonResponse({'error': f'DART 접속 실패: {exc}'}, status=500)

    nodes = br.pick_nodes(_dart_top_nodes(main.text), sections)[0]
    if not nodes:
        return JsonResponse({
            'error': f'보고서에서 "{", ".join(sections)}" 절을 찾지 못했습니다. '
                     f'프롬프트의 {{사업보고서:…}} 에 적은 절 이름을 확인하세요.',
        }, status=404)

    parts, total = [], 0
    try:
        for node in nodes:
            text = _dart_viewer_text(session, {
                'rcpNo': node['rcpNo'] or rcept_no, 'dcmNo': node['dcmNo'],
                'eleId': node['eleId'], 'offset': node['offset'],
                'length': node['length'], 'dtd': node['dtd'],
            })
            if not text:
                continue
            parts.append(f'### {node["text"]}\n\n{text}')
            total += len(text)
            if total > br.MAX_CHARS:
                break
    except requests.RequestException as exc:
        return JsonResponse({'error': f'보고서 조회 실패: {exc}'}, status=500)

    if total > br.MAX_CHARS:
        # 자르지 않고 거절한다. 앞부분만 든 채로 다 봤다고 착각하는 편이 더 나쁘다.
        return JsonResponse({
            'error': f'본문이 너무 깁니다 ({total:,}자, 한도 {br.MAX_CHARS:,}자). '
                     f'절을 좁혀 지정하세요 — "재무에 관한 사항"은 그 자체로 2MB 가 넘습니다.',
        }, status=413)
    if not parts:
        return JsonResponse({'error': '보고서 본문을 추출할 수 없습니다.'}, status=404)

    return JsonResponse({
        'success': True,
        'title': _re.sub(r'\s+', ' ', gongsi.title).strip(),
        'date': f'{gongsi.date:%Y-%m-%d}',
        'link': gongsi.link,
        'sections': [n['text'] for n in nodes],
        'content_length': total,
        'content': '\n\n'.join(parts),
    })




def settings(request):
    """설정 페이지"""
    from .models import ThemeCategory, SystemSetting

    categories = ThemeCategory.objects.prefetch_related('themes').all()

    # 저장된 프롬프트 불러오기
    saved_prompts = {}
    for setting in SystemSetting.objects.filter(key__startswith='prompt_'):
        saved_prompts[setting.key] = setting.value

    # 핵심브리핑 데이터 타입 불러오기
    try:
        saved_types = SystemSetting.objects.get(key='briefing_data_types').value
        briefing_data_types = [t for t in saved_types.split(',') if t]  # 빈 문자열 제거
        if not briefing_data_types:
            briefing_data_types = ['analysis', 'key_briefing', 'report', 'youtube', 'news', 'telegram', 'memo']
    except SystemSetting.DoesNotExist:
        # 기본값: 모든 타입 선택
        briefing_data_types = ['analysis', 'key_briefing', 'report', 'youtube', 'news', 'telegram', 'memo']

    context = {
        'categories': categories,
        'saved_prompts': saved_prompts,
        'briefing_data_types': briefing_data_types,
        'telegram_channels': {str(k): v for k, v in TELEGRAM_CHANNELS.items()},
    }
    return render(request, 'stocks/settings.html', context)


def etf(request):
    """ETF 페이지"""
    from .models import InfoETF, DailyChartETF

    # 관심/대기로 분류된 ETF - 이름 순
    etfs = list(
        InfoETF.objects.filter(is_active=True)
        .exclude(interest_level__isnull=True)
        .order_by('name')
    )

    # 보유는 자산에서 파생한다 (종목과 같은 규칙 — 보유가 관심/대기보다 앞선다)
    etf_holding_codes = set(
        Holding.objects.filter(info_etf__isnull=False).values_list('info_etf__code', flat=True)
    )

    def etf_level_of(item):
        return 'holding' if item.code in etf_holding_codes else item.interest_level

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
        # 이평 배열과 눌림목 — 종목 상세도 같은 계산을 쓴다 (stock_signal)
        ma_align = stock_signal.ma_alignment(daily_data)
        pullback, pullback_label = stock_signal.pullback(daily_data, ma_align)

        status_etfs.append({
            'etf': etf_item,
            'level': etf_level_of(etf_item),
            'ma_align': ma_align,
            'vol_high_20': today_vol > 0 and today_vol >= max_vol_20,
            'vol_high_60': today_vol > 0 and today_vol >= max_vol_60,
            'is_bullish': today.closing_price >= today.opening_price if today.opening_price else True,
            'pullback': pullback,
            'pullback_label': pullback_label,
        })

    context = {
        'etfs': etfs,
        'status_etfs': status_etfs,
    }
    return render(request, 'stocks/etf.html', context)


def etf_detail(request, code):
    """ETF 상세 페이지"""
    from .models import InfoETF, DailyChartETF, WeeklyChartETF, MonthlyChartETF

    etf = get_object_or_404(InfoETF, code=code)

    # 보유는 자산에서 파생한다 (수동 플래그를 쓰지 않는다)
    is_holding = Holding.objects.filter(info_etf=etf).exists()

    # POST 처리 - 관심 단계·추적 저장
    if request.method == 'POST':
        level = request.POST.get('interest_level', '')
        # 보유 중이면 관심을 뗄 수 없다. 종목과 같은 이유다.
        if not level and is_holding:
            messages.error(request, f'{etf.name}은(는) 보유 중이라 관심을 해제할 수 없습니다.')
            return redirect('stocks:etf_detail', code=code)
        etf.interest_level = level or None
        etf.is_tracking = request.POST.get('is_tracking') == 'on'
        etf.save(update_fields=['interest_level', 'is_tracking'])
        messages.success(request, '저장되었습니다.')
        return redirect('stocks:etf_detail', code=code)

    # 일봉 차트 데이터 (표시 240일 + 120일선 계산용 120일)
    daily_charts = list(DailyChartETF.objects.filter(
        etf=etf
    ).order_by('-date')[:360])
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

    # 주봉 차트 데이터 (표시 104주 + 60주선 계산용 60주)
    weekly_charts = list(WeeklyChartETF.objects.filter(
        etf=etf
    ).order_by('-date')[:164])
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

    # 월봉 차트 데이터 (표시 72개월 + 12개월선 계산용 12개월)
    monthly_charts = list(MonthlyChartETF.objects.filter(
        etf=etf
    ).order_by('-date')[:84])
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
        'is_holding': is_holding,
        'interest_choices': InfoETF._meta.get_field('interest_level').choices,
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
def stock_question_report_save(request):
    """종목 질문리포트 저장 API"""
    from .models import Info, StockQuestionReport

    stock_code = request.POST.get('stock_code', '')
    question = request.POST.get('question', '').strip()
    report = request.POST.get('report', '')
    # AI 답변은 마크다운으로 온다. 옛 기본값이 html 이라 새 리서치가
    # 마크다운을 못 그린 채로 생겼다.
    report_type = request.POST.get('report_type', 'markdown')
    report_id = request.POST.get('report_id') or ''

    if not stock_code:
        return JsonResponse({'success': False, 'error': '종목코드가 필요합니다.'})

    if not question:
        return JsonResponse({'success': False, 'error': '질문을 입력해주세요.'})

    # report_type 유효성 검사
    if report_type not in ('html', 'markdown'):
        report_type = 'markdown'

    try:
        stock = Info.objects.get(code=stock_code)
    except Info.DoesNotExist:
        return JsonResponse({'success': False, 'error': '종목을 찾을 수 없습니다.'})

    # 넘어온 칸만 고친다. 붙여넣기 창은 리포트만, 질문·프롬프트 창은
    # 질문과 프롬프트만 보낸다 — 안 보낸 칸을 빈 값으로 덮으면 지운다.
    fields = {}
    if 'report' in request.POST:
        fields['report'] = report
        fields['report_type'] = report_type
    if 'ai_question' in request.POST:
        fields['ai_question'] = request.POST.get('ai_question', '')

    # report_id 가 오면 그 행을 고친다. 질문 이름을 바꾸는 길은 이것뿐이다 —
    # (종목, 질문) 으로 찾으면 새 이름의 행이 하나 더 생기고 옛것이 남는다.
    if report_id:
        qr = StockQuestionReport.objects.filter(id=report_id, stock=stock).first()
        if not qr:
            return JsonResponse({'success': False, 'error': '리서치를 찾을 수 없습니다.'})
        if (qr.question != question
                and StockQuestionReport.objects.filter(stock=stock, question=question).exists()):
            return JsonResponse({'success': False,
                                 'error': f'"{question}" 리서치가 이미 있습니다.'})
        qr.question = question
        for key, value in fields.items():
            setattr(qr, key, value)
        qr.save()
        return JsonResponse({'success': True, 'id': qr.id, 'created': False,
                             'report_type': qr.report_type})

    # 한 종목의 한 질문은 하나다. 화면이 프롬프트를 칸으로 놓고 답을 채우는
    # 방식이라, 같은 칸에 두 번 붙여넣으면 새로 쌓이는 게 아니라 덮어써야
    # 한다. AI 판단이 같은 기준일에 덮어쓰는 것과 같다.
    fields.setdefault('report', report)
    fields.setdefault('report_type', report_type)
    qr, created = StockQuestionReport.objects.update_or_create(
        stock=stock, question=question, defaults=fields,
    )

    return JsonResponse({'success': True, 'id': qr.id, 'created': created,
                         'report_type': qr.report_type})


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


def research_text(stock, question):
    """리서치 칸 하나의 내용. 핵심브리핑처럼 옛 필드를 대신한다."""
    from .models import StockQuestionReport

    if not stock:
        return ''
    row = StockQuestionReport.objects.filter(stock=stock, question=question).first()
    return (row.report or '') if row else ''


def stock_question_report_slot(request, code):
    """
    아직 안 채운 칸.

    종목 화면의 흐린 칸을 누르면 여기로 온다. 저장된 리서치가 없으므로
    행을 만들지 않고 빈 채로 그린다 — 여기서 행을 만들어 버리면 내용이
    없는데도 칸이 '채워짐'으로 보인다. 붙여넣어 저장하는 순간 생긴다.
    """
    from .models import StockQuestionReport

    stock = get_object_or_404(Info, code=code)
    question = (request.GET.get('q') or '').strip()
    # 이름이 없으면 '일반'을 새로 만드는 길이다. 이때는 행을 찾지 않는다.
    existing = (StockQuestionReport.objects.filter(stock=stock, question=question).first()
                if question else None)
    if existing:
        return redirect('stocks:stock_question_report_detail', report_id=existing.id)
    return stock_question_report_detail(
        request, None, qr=StockQuestionReport(stock=stock, question=question))


def stock_question_report_detail(request, report_id, qr=None):
    """리서치 상세. 칸이 비어 있으면 qr 은 저장 안 된 빈 객체다."""
    from .models import StockQuestionReport, ResearchPrompt, QuickReport, SystemSetting
    if qr is None:
        qr = get_object_or_404(StockQuestionReport, id=report_id)

    if request.method == 'POST':
        # 일반 질문의 '질문·프롬프트' 폼. 리포트는 붙여넣기 창이 따로 저장하므로
        # 여기서 건드리지 않는다 — 넘어오지 않은 칸을 빈 값으로 덮으면 지운다.
        for field in ('question', 'report', 'ai_question'):
            if field in request.POST:
                value = request.POST[field]
                setattr(qr, field, value.strip() if field == 'question' else value)
        report_type = request.POST.get('report_type')
        if report_type in ('html', 'markdown'):
            qr.report_type = report_type
        qr.save()
        return redirect('stocks:stock_question_report_detail', report_id=qr.id)

    from . import research_slots

    # 이 리서치의 프롬프트 하나. 없으면(직접 만든 질문) None.
    #
    # 예전에는 여기서 프롬프트를 스물두 개 늘어놓고 그중에서 고르게 했다.
    # 이제 고르는 일은 종목 화면의 빈 칸이 한다 — 칸을 누르면 그 칸의
    # 리서치로 오므로, 여기서는 이름이 같은 것 하나면 된다.
    own_prompt = research_slots.find_prompt(qr.question)
    slot_alert = research_slots.slot_alert(qr.stock, qr, own_prompt)
    # 일반 리서치는 프롬프트를 직접 쓴다. 무엇을 쓸 수 있는지 창에서 보여준다.
    from . import research_vars

    theme_category_name = ''
    theme_name = ''
    if qr.stock:
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
        # 향후 이벤트는 리서치 '이벤트' 칸이다
        _events_text = research_text(qr.stock, '이벤트') or research_text(qr.stock, '향후 이벤트')

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
            'key_briefing': research_text(qr.stock, '핵심브리핑'),
            'future_events': _events_text,
            # 핵심브리핑이 리서치 칸으로 내려오면서 필요해진 것들. 리서치가
            # 아니라 종목에 붙어 있는 분석이라 이름으로 끌어올 수 없다.
            'financial_analysis': qr.stock.financial_analysis_v2 or '',
            'consensus_analysis': qr.stock.consensus_analysis or '',
            'base_quarter': _get_latest_quarter(qr.stock),
            **tech,
            **{f'기업분석: {q}': r for q, r in _qr_map.items()},
        }

    prompt_summary = SystemSetting.objects.filter(key='prompt_summary').values_list('value', flat=True).first() or ''

    # 전체내용복사용 데이터
    all_content_data = {}
    if qr.stock:
        _all_reports = StockQuestionReport.objects.filter(stock=qr.stock).exclude(id=qr.id)
        _groups = {g['name']: {s['question'] for s in g['slots']}
                   for g in research_slots.build_groups(qr.stock, _all_reports)[0]}
        _common_set = _groups.get('기업분석', set())
        _quick_set = _groups.get('상황추적', set()) | _groups.get('투자판단', set())
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
            'key_briefing': research_text(qr.stock, '핵심브리핑'),
            'financial_analysis': qr.stock.financial_analysis_v2 or '',
            'consensus_analysis': qr.stock.consensus_analysis or '',
        }

    return render(request, 'stocks/question_report_detail.html', {
        'qr': qr,
        'own_prompt': own_prompt,
        'slot_alert': slot_alert,
        'research_var_groups': research_vars.GROUPS,
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
def material_save(request, code):
    """
    자료 저장 API. 링크와 내용을 받는다.

    같은 링크를 다시 저장하면 내용을 덮어쓴다. 요약을 다시 떠서 붙여넣는
    일이 흔한데, 그때마다 줄이 하나씩 늘면 목록이 금방 지저분해진다.
    """
    from .models import Material

    stock = get_object_or_404(Info, code=code)
    link = (request.POST.get('link') or '').strip()
    content = (request.POST.get('content') or '').strip()
    if not content:
        return JsonResponse({'success': False, 'error': '내용을 입력하세요.'})

    existing = Material.objects.filter(stock=stock, link=link).first() if link else None
    if existing:
        existing.content = content
        existing.save(update_fields=['content'])
        material, replaced = existing, True
    else:
        material = Material.objects.create(stock=stock, link=link, content=content)
        replaced = False

    return JsonResponse({
        'success': True, 'replaced': replaced,
        'material': _material_json(material),
        'count': Material.objects.filter(stock=stock).count(),
    })


@require_POST
def material_update(request, material_id):
    """자료 내용 수정 API. 목록에서 펼친 자리에서 그대로 고친다."""
    from .models import Material

    material = get_object_or_404(Material, id=material_id)
    content = (request.POST.get('content') or '').strip()
    if not content:
        return JsonResponse({'success': False, 'error': '내용을 입력하세요.'})
    material.content = content
    material.save(update_fields=['content'])
    return JsonResponse({'success': True, 'material': _material_json(material)})


@require_POST
def material_delete(request, material_id):
    """자료 삭제 API"""
    from .models import Material

    material = get_object_or_404(Material, id=material_id)
    code = material.stock.code
    material.delete()
    return JsonResponse({
        'success': True,
        'count': Material.objects.filter(stock__code=code).count(),
    })


def _material_json(material):
    """저장 직후 화면에 줄을 그리는 데 필요한 것만."""
    return {
        'id': material.id,
        'link': material.link,
        'content': material.content,
        'head': material.head,
        'kind': material.kind,
        'date': material.created_at.strftime('%y.%m.%d'),
    }


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


# ============ AI 판단 ============

@require_POST
def ai_note_parse(request):
    """붙여넣은 답변에서 한 줄 결론·스탠스를 뽑아 돌려준다 (저장 전 미리보기)"""
    from .ai_note import parse

    return JsonResponse({'success': True, **parse(request.POST.get('content', ''))})


@require_POST
def ai_note_save(request):
    """
    AI 판단 저장. 시황·리포트·수급·공시가 같은 문을 쓴다.

    기준일은 클라이언트를 믿지 않고 서버에서 정한다 — 그 자리의 최신
    데이터 날짜다(시황은 지표, 종목은 일봉). 같은 기준일에 다시 저장하면
    덮어쓴다. 사람이 날짜를 고르게 하면 어제 것을 오늘로 적는 실수가 난다.
    """
    from .ai_note import KINDS, basis_date, parse
    from .models import AiNote

    kind = (request.POST.get('kind') or '').strip()
    key = (request.POST.get('key') or '').strip()
    content = (request.POST.get('content') or '').strip()
    if kind not in KINDS:
        return JsonResponse({'success': False, 'error': f'알 수 없는 자리: {kind}'})
    if kind == 'market':
        key = key.upper()
    if not key:
        return JsonResponse({'success': False, 'error': '대상이 없습니다.'})
    if not content:
        return JsonResponse({'success': False, 'error': '답변 내용이 비어 있습니다.'})

    date = basis_date(kind, key)
    if not date:
        return JsonResponse({'success': False, 'error': '데이터가 아직 없어 기준일을 정할 수 없습니다.'})

    auto = parse(content)
    AiNote.objects.update_or_create(
        kind=kind, key=key, date=date,
        defaults={
            # 사람이 고쳤으면 그 값을, 안 건드렸으면 자동 추출값을 쓴다
            'headline': (request.POST.get('headline') or auto['headline'])[:300],
            'stance': request.POST.get('stance') or auto['stance'],
            'content': content,
        },
    )
    return JsonResponse({'success': True, 'date': date.strftime('%Y-%m-%d')})


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



