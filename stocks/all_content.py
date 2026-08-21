# -*- coding: utf-8 -*-
"""
'전체내용복사' — 이 종목에 대해 저장해 둔 것을 전부 이어붙인다.

    ## 주가 통계 / 기업분석: 사업모델 / 상황추적: 실적확인 /
    ## 투자판단: 핵심브리핑 / 일반: … / 재무분석 / 컨센서스분석 /
    ## 수급 데이터 / 수급분석 / 공시 / 리포트 / 자료

예전에는 종목 화면을 그릴 때마다 이것을 만들어 페이지에 실어 보냈다.
버튼을 누를 때만 쓰는 값인데 열 때마다 따라온 셈이다. 동성화인텍이
69K자였고 json_script 가 한글을 유니코드 이스케이프로 바꾸면서 페이지 안에서는
292KB 였다 — 871KB 짜리 화면의 34% 다.

이제 버튼을 누르면 그때 만들어 준다. {사업보고서}·{공시본문}과 같은 방식이다.
"""


def build(stock):
    from .models import (
        DailyChart, Gongsi, InvestorTrend, Material, Report, StockQuestionReport,
    )
    from . import gongsi_signal, research_slots

    # 종목 화면과 똑같이 뽑는다 — 420일을 받아 이평을 내고 360일로 자른다.
    # 순서가 바뀌면 52주 고저와 이평 대비 값이 달라진다.
    daily_charts = list(DailyChart.objects.filter(stock=stock).order_by('-date')[:420])
    daily_charts.reverse()

    def _ma(data, period):
        if len(data) < period:
            return None
        return round(sum(d.closing_price for d in data[-period:]) / period)

    ma10_value = _ma(daily_charts, 10)
    ma20_value = _ma(daily_charts, 20)
    ma60_value = _ma(daily_charts, 60)
    daily_charts = daily_charts[-360:]
    question_reports = list(StockQuestionReport.objects.filter(stock=stock))
    research_groups, custom_question_reports, _ = research_slots.build_groups(
        stock, question_reports)
    # 수급 표는 다음(daum) 값이 있는 날만 쓰고, 주가·등락률·거래량은 일봉에서
    # 끌어다 붙인다. 종목 화면이 하던 것과 같다.
    _daum = [t for t in InvestorTrend.objects.filter(stock=stock).order_by('-date')[:60]
             if t.daum_foreign is not None or t.daum_institution is not None]
    _chart = {dc.date: dc for dc in
              DailyChart.objects.filter(stock=stock, date__in=[t.date for t in _daum])}
    investor_trends_daum = []
    for t in _daum:
        dc = _chart.get(t.date)
        t.closing_price = dc.closing_price if dc else None
        t.trading_volume = dc.trading_volume if dc else None
        if dc and dc.closing_price and dc.price_change:
            prev = dc.closing_price - dc.price_change
            t.change_rate = round((dc.price_change / prev) * 100, 2) if prev else 0
        else:
            t.change_rate = None
        investor_trends_daum.append(t)
    gongsi_list = list(Gongsi.objects.filter(stock=stock).order_by('-date')[:20])
    for g in gongsi_list:
        g.cat = gongsi_signal.classify(g.title)
    reports = list(Report.objects.filter(stock=stock).order_by('-date')[:20])
    materials = list(Material.objects.filter(stock=stock).order_by('-created_at'))

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
    return '\n\n---\n\n'.join(all_content_sections) if all_content_sections else ''
