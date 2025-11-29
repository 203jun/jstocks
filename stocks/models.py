from django.db import models


class Info(models.Model):
    """종목 기본 정보"""

    code = models.CharField(max_length=10, primary_key=True, verbose_name='종목코드')
    name = models.CharField(max_length=100, verbose_name='종목명')
    market = models.CharField(
        max_length=10,
        choices=[
            ('KOSPI', 'KOSPI'),
            ('KOSDAQ', 'KOSDAQ'),
            ('KONEX', 'KONEX'),
        ],
        verbose_name='시장구분'
    )
    market_cap = models.BigIntegerField(null=True, blank=True, verbose_name='시가총액')
    is_active = models.BooleanField(default=True, verbose_name='활성화')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='생성일시')

    class Meta:
        db_table = 'info'
        verbose_name = '종목정보'
        verbose_name_plural = '종목정보'
        ordering = ['code']

    def __str__(self):
        return f"{self.name} ({self.code})"


class InvestorTrend(models.Model):
    """
    투자자별 매매동향 (일별)

    키움 API ka10059 (종목별투자자기관별요청) 응답 데이터 저장
    각 종목의 일자별 투자자(개인/외국인/기관) 순매수 데이터를 저장합니다.

    - 개인/외국인/기관의 순매수량 (양수: 순매수, 음수: 순매도)
    - 기관을 세부적으로 금융투자/보험/투신/은행/연기금/사모펀드/기타법인으로 구분
    """

    # === 기본 정보 ===
    stock = models.ForeignKey(
        Info,
        on_delete=models.CASCADE,
        verbose_name='종목',
        help_text='종목 정보 (Info 모델 참조)',
        db_index=True
    )
    date = models.DateField(
        verbose_name='일자',
        help_text='거래일자 (YYYYMMDD)',
        db_index=True
    )

    # === 투자자별 순매수 (핵심 데이터) ===
    individual = models.BigIntegerField(
        verbose_name='개인 순매수',
        help_text='개인투자자 순매수량 (API: ind_invsr) - 양수: 순매수, 음수: 순매도'
    )
    foreign = models.BigIntegerField(
        verbose_name='외국인 순매수',
        help_text='외국인투자자 순매수량 (API: frgnr_invsr) - 양수: 순매수, 음수: 순매도'
    )
    institution = models.BigIntegerField(
        verbose_name='기관 순매수',
        help_text='기관계 전체 순매수량 (API: orgn) - 양수: 순매수, 음수: 순매도'
    )
    domestic_foreign = models.BigIntegerField(
        verbose_name='내외국인 순매수',
        help_text='내외국인 순매수량 (API: natfor) - 양수: 순매수, 음수: 순매도'
    )

    # === 기관 세부 구분 ===
    financial = models.BigIntegerField(
        verbose_name='금융투자 순매수',
        help_text='금융투자 순매수량 (API: fnnc_invt) - 증권사 등',
        null=True,
        blank=True
    )
    insurance = models.BigIntegerField(
        verbose_name='보험 순매수',
        help_text='보험 순매수량 (API: insrnc)',
        null=True,
        blank=True
    )
    investment_trust = models.BigIntegerField(
        verbose_name='투신 순매수',
        help_text='투신(투자신탁) 순매수량 (API: invtrt)',
        null=True,
        blank=True
    )
    other_finance = models.BigIntegerField(
        verbose_name='기타금융 순매수',
        help_text='기타금융 순매수량 (API: etc_fnnc)',
        null=True,
        blank=True
    )
    bank = models.BigIntegerField(
        verbose_name='은행 순매수',
        help_text='은행 순매수량 (API: bank)',
        null=True,
        blank=True
    )
    pension_fund = models.BigIntegerField(
        verbose_name='연기금 순매수',
        help_text='연기금 등 순매수량 (API: penfnd_etc) - 국민연금 등',
        null=True,
        blank=True
    )
    private_fund = models.BigIntegerField(
        verbose_name='사모펀드 순매수',
        help_text='사모펀드 순매수량 (API: samo_fund)',
        null=True,
        blank=True
    )
    other_corporation = models.BigIntegerField(
        verbose_name='기타법인 순매수',
        help_text='기타법인 순매수량 (API: etc_corp)',
        null=True,
        blank=True
    )

    # === 메타 정보 ===
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성일시'
    )

    class Meta:
        db_table = 'investor_trend'
        verbose_name = '투자자별매매동향'
        verbose_name_plural = '투자자별매매동향'
        ordering = ['-date', 'stock']
        unique_together = [('stock', 'date')]  # 종목+날짜 조합은 유일
        indexes = [
            models.Index(fields=['stock', '-date']),  # 종목별 최신순 조회용
            models.Index(fields=['-date']),           # 날짜별 조회용
        ]

    def __str__(self):
        return f"{self.stock.name} - {self.date} (개인: {self.individual:,}, 외국인: {self.foreign:,}, 기관: {self.institution:,})"


class DailyChart(models.Model):
    """
    주식 일봉 차트 데이터

    키움 API ka10081 (주식일봉차트조회요청) 응답 데이터 저장
    각 종목의 일자별 시가/고가/저가/종가(OHLC) 및 거래량/거래대금 데이터를 저장합니다.

    - 일봉 기준 데이터 (1일 단위)
    - OHLC: Open(시가), High(고가), Low(저가), Close(종가=현재가)
    """

    # === 기본 정보 ===
    stock = models.ForeignKey(
        Info,
        on_delete=models.CASCADE,
        verbose_name='종목',
        help_text='종목 정보 (Info 모델 참조)',
        db_index=True
    )
    date = models.DateField(
        verbose_name='일자',
        help_text='거래일자 (API: dt)',
        db_index=True
    )

    # === 가격 정보 (OHLC) ===
    opening_price = models.BigIntegerField(
        verbose_name='시가',
        help_text='시가 (API: open_pric) - 장 시작 가격'
    )
    high_price = models.BigIntegerField(
        verbose_name='고가',
        help_text='고가 (API: high_pric) - 당일 최고가'
    )
    low_price = models.BigIntegerField(
        verbose_name='저가',
        help_text='저가 (API: low_pric) - 당일 최저가'
    )
    closing_price = models.BigIntegerField(
        verbose_name='종가',
        help_text='종가/현재가 (API: cur_prc) - 장 마감 가격'
    )
    price_change = models.BigIntegerField(
        verbose_name='전일대비',
        help_text='전일대비 (API: pred_pre) - 현재가 - 전일종가, 양수: 상승, 음수: 하락'
    )

    # === 거래 정보 ===
    trading_volume = models.BigIntegerField(
        verbose_name='거래량',
        help_text='거래량 (API: trde_qty) - 당일 총 거래량(주)'
    )
    trading_value = models.BigIntegerField(
        verbose_name='거래대금',
        help_text='거래대금 (API: trde_prica) - 당일 총 거래금액(백만원)'
    )

    # === 메타 정보 ===
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성일시'
    )

    class Meta:
        db_table = 'daily_chart'
        verbose_name = '일봉차트'
        verbose_name_plural = '일봉차트'
        ordering = ['-date', 'stock']
        unique_together = [('stock', 'date')]  # 종목+날짜 조합은 유일
        indexes = [
            models.Index(fields=['stock', '-date']),  # 종목별 최신순 조회용
            models.Index(fields=['-date']),           # 날짜별 조회용
        ]

    def __str__(self):
        return f"{self.stock.name} - {self.date} (종가: {self.closing_price:,}원)"


class WeeklyChart(models.Model):
    """
    주식 주봉 차트 데이터

    키움 API ka10082 (주식주봉차트조회요청) 응답 데이터 저장
    각 종목의 주별 시가/고가/저가/종가(OHLC) 및 거래량/거래대금 데이터를 저장합니다.

    - 주봉 기준 데이터 (1주 단위)
    - OHLC: Open(시가), High(고가), Low(저가), Close(종가=현재가)
    """

    # === 기본 정보 ===
    stock = models.ForeignKey(
        Info,
        on_delete=models.CASCADE,
        verbose_name='종목',
        help_text='종목 정보 (Info 모델 참조)',
        db_index=True
    )
    date = models.DateField(
        verbose_name='일자',
        help_text='주봉 기준일자 (API: dt) - 해당 주의 마지막 거래일',
        db_index=True
    )

    # === 가격 정보 (OHLC) ===
    opening_price = models.BigIntegerField(
        verbose_name='시가',
        help_text='시가 (API: open_pric) - 해당 주 시작 가격'
    )
    high_price = models.BigIntegerField(
        verbose_name='고가',
        help_text='고가 (API: high_pric) - 해당 주 최고가'
    )
    low_price = models.BigIntegerField(
        verbose_name='저가',
        help_text='저가 (API: low_pric) - 해당 주 최저가'
    )
    closing_price = models.BigIntegerField(
        verbose_name='종가',
        help_text='종가/현재가 (API: cur_prc) - 해당 주 마감 가격'
    )
    price_change = models.BigIntegerField(
        verbose_name='전주대비',
        help_text='전주대비 (API: pred_pre) - 현재가 - 전주종가, 양수: 상승, 음수: 하락'
    )

    # === 거래 정보 ===
    trading_volume = models.BigIntegerField(
        verbose_name='거래량',
        help_text='거래량 (API: trde_qty) - 해당 주 총 거래량(주)'
    )
    trading_value = models.BigIntegerField(
        verbose_name='거래대금',
        help_text='거래대금 (API: trde_prica) - 해당 주 총 거래금액(백만원)'
    )

    # === 메타 정보 ===
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성일시'
    )

    class Meta:
        db_table = 'weekly_chart'
        verbose_name = '주봉차트'
        verbose_name_plural = '주봉차트'
        ordering = ['-date', 'stock']
        unique_together = [('stock', 'date')]  # 종목+날짜 조합은 유일
        indexes = [
            models.Index(fields=['stock', '-date']),  # 종목별 최신순 조회용
            models.Index(fields=['-date']),           # 날짜별 조회용
        ]

    def __str__(self):
        return f"{self.stock.name} - {self.date} (종가: {self.closing_price:,}원)"


class MonthlyChart(models.Model):
    """
    주식 월봉 차트 데이터

    키움 API ka10083 (주식월봉차트조회요청) 응답 데이터 저장
    각 종목의 월별 시가/고가/저가/종가(OHLC) 및 거래량/거래대금 데이터를 저장합니다.

    - 월봉 기준 데이터 (1개월 단위)
    - OHLC: Open(시가), High(고가), Low(저가), Close(종가=현재가)
    """

    # === 기본 정보 ===
    stock = models.ForeignKey(
        Info,
        on_delete=models.CASCADE,
        verbose_name='종목',
        help_text='종목 정보 (Info 모델 참조)',
        db_index=True
    )
    date = models.DateField(
        verbose_name='일자',
        help_text='월봉 기준일자 (API: dt) - 해당 월의 마지막 거래일',
        db_index=True
    )

    # === 가격 정보 (OHLC) ===
    opening_price = models.BigIntegerField(
        verbose_name='시가',
        help_text='시가 (API: open_pric) - 해당 월 시작 가격'
    )
    high_price = models.BigIntegerField(
        verbose_name='고가',
        help_text='고가 (API: high_pric) - 해당 월 최고가'
    )
    low_price = models.BigIntegerField(
        verbose_name='저가',
        help_text='저가 (API: low_pric) - 해당 월 최저가'
    )
    closing_price = models.BigIntegerField(
        verbose_name='종가',
        help_text='종가/현재가 (API: cur_prc) - 해당 월 마감 가격'
    )
    price_change = models.BigIntegerField(
        verbose_name='전월대비',
        help_text='전월대비 (API: pred_pre) - 현재가 - 전월종가, 양수: 상승, 음수: 하락'
    )

    # === 거래 정보 ===
    trading_volume = models.BigIntegerField(
        verbose_name='거래량',
        help_text='거래량 (API: trde_qty) - 해당 월 총 거래량(주)'
    )
    trading_value = models.BigIntegerField(
        verbose_name='거래대금',
        help_text='거래대금 (API: trde_prica) - 해당 월 총 거래금액(백만원)'
    )

    # === 메타 정보 ===
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성일시'
    )

    class Meta:
        db_table = 'monthly_chart'
        verbose_name = '월봉차트'
        verbose_name_plural = '월봉차트'
        ordering = ['-date', 'stock']
        unique_together = [('stock', 'date')]  # 종목+날짜 조합은 유일
        indexes = [
            models.Index(fields=['stock', '-date']),  # 종목별 최신순 조회용
            models.Index(fields=['-date']),           # 날짜별 조회용
        ]

    def __str__(self):
        return f"{self.stock.name} - {self.date} (종가: {self.closing_price:,}원)"
