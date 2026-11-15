"""현황 표의 행을 만든다.

대시보드(종목 화면)와 공유 페이지가 같은 표를 보여주므로, 행을 만드는 일은
여기 한 곳에만 둔다. 예전에는 views.index 안에 이백 줄로 들어 있어서
다른 화면에서 같은 표를 쓸 방법이 없었다.
"""
from django.db.models import Q

from . import stock_signal
from .gongsi_signal import classify as _classify_gongsi
from .models import (
    DailyChart, Gongsi, Holding, InvestorTrend, Report, ShortSelling,
)


def build_status_rows(target_stocks, holding_codes, card_c_stocks=None, include_etf=True):
    """현황 표 행 목록을 돌려준다.

    target_stocks  표에 올릴 종목 (Info) — 정렬된 순서 그대로 쓴다
    holding_codes  보유로 볼 종목코드 집합. 빈 집합을 주면 보유 표시를 하지 않는다
    card_c_stocks  이미 계산해 둔 신호추적 결과가 있으면 재활용한다
    include_etf    ETF 행을 같은 표에 섞을지
    """
    card_c_stocks = card_c_stocks or []

    def level_of(stock):
        """화면 분류는 하나만 — 보유가 관심/대기보다 앞선다"""
        return 'holding' if stock.code in holding_codes else stock.interest_level

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

    if not include_etf:
        return status_stocks

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

    return status_stocks


def status_block_text(item):
    """현황 한 종목을 프롬프트에 붙일 글로 적는다.

    표에 배지로 그리는 것과 같은 내용이다. 화면과 프롬프트가 다른 말을
    하면 안 되므로 여기 한 곳에서 만든다.
    """
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
    return '\n'.join(lines)
