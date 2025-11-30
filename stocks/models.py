from django.db import models


class Info(models.Model):
    """
    종목 기본 정보

    ※ 테마와의 관계:
    - 하나의 종목은 여러 테마에 속할 수 있음 (N:M)
    - 예: 삼성전자 → 반도체, 대형주, 배당주 등
    - themes 필드로 연결된 테마 조회 가능
    - 역참조: theme.stocks.all() → 해당 테마에 속한 모든 종목

    ※ 주의:
    - Theme 모델은 시계열 데이터 (code + date)
    - Info.themes는 테마 코드별로 최신 데이터와 연결하는 것을 권장
    - 종목-테마 매핑은 별도 API로 채워집니다
    """

    # === 기본 정보 ===
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
    is_active = models.BooleanField(default=True, verbose_name='활성화')

    # === 주식/시가총액 정보 ===
    listed_shares = models.BigIntegerField(null=True, blank=True, verbose_name='상장주식')
    market_cap = models.BigIntegerField(null=True, blank=True, verbose_name='시가총액')
    listed_ratio = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, verbose_name='유통비율')

    # === 투자 지표 ===
    credit_ratio = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, verbose_name='신용비율')
    foreign_exhaustion = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, verbose_name='외인소진률')

    # === 재무 지표 ===
    per = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='PER')
    eps = models.BigIntegerField(null=True, blank=True, verbose_name='EPS')
    roe = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, verbose_name='ROE')
    pbr = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='PBR')
    ev = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='EV')
    bps = models.BigIntegerField(null=True, blank=True, verbose_name='BPS')

    # === 실적 정보 ===
    sales = models.BigIntegerField(null=True, blank=True, verbose_name='매출액')
    operating_profit = models.BigIntegerField(null=True, blank=True, verbose_name='영업이익')
    net_income = models.BigIntegerField(null=True, blank=True, verbose_name='당기순이익')

    # === 가격 정보 ===
    year_high = models.BigIntegerField(null=True, blank=True, verbose_name='연중최고')
    year_low = models.BigIntegerField(null=True, blank=True, verbose_name='연중최저')
    high_250 = models.BigIntegerField(null=True, blank=True, verbose_name='250최고')
    low_250 = models.BigIntegerField(null=True, blank=True, verbose_name='250최저')
    high_price = models.BigIntegerField(null=True, blank=True, verbose_name='고가')
    open_price = models.BigIntegerField(null=True, blank=True, verbose_name='시가')
    low_price = models.BigIntegerField(null=True, blank=True, verbose_name='저가')
    current_price = models.BigIntegerField(null=True, blank=True, verbose_name='현재가')
    price_change = models.BigIntegerField(null=True, blank=True, verbose_name='전일대비')
    change_rate = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, verbose_name='등락율')

    # === 거래 정보 ===
    volume = models.BigIntegerField(null=True, blank=True, verbose_name='거래량')
    volume_change = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='거래대비')

    # === 시간 정보 ===
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='생성일시')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='수정일시')

    # === 테마 관계 ===
    themes = models.ManyToManyField(
        'Theme',
        related_name='stocks',
        blank=True,
        verbose_name='소속 테마',
        help_text='이 종목이 속한 테마들 (예: 반도체, AI, 2차전지 등)'
    )

    # === 업종 관계 ===
    sectors = models.ManyToManyField(
        'Sector',
        related_name='stocks',
        blank=True,
        verbose_name='소속 업종',
        help_text='이 종목이 속한 업종들 (예: 종합, 대형주, 반도체업종 등)'
    )

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


class ShortSelling(models.Model):
    """
    공매도 추이 데이터

    키움 API ka10014 (공매도추이요청) 응답 데이터 저장
    각 종목의 일자별 공매도량, 거래비중, 누적공매도량 등의 데이터를 저장합니다.

    - 일별 공매도 거래 정보
    - 공매도량, 공매도 거래대금, 공매도 평균가
    - 전체 거래 대비 공매도 비중 파악 가능
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

    # === 거래량 정보 ===
    trading_volume = models.BigIntegerField(
        verbose_name='거래량',
        help_text='거래량 (API: trde_qty) - 당일 전체 거래량(주)'
    )
    short_volume = models.BigIntegerField(
        verbose_name='공매도량',
        help_text='공매도량 (API: shrts_qty) - 당일 공매도 거래량(주)'
    )
    cumulative_short_volume = models.BigIntegerField(
        verbose_name='누적공매도량',
        help_text='누적공매도량 (API: ovr_shrts_qty) - 설정 기간의 공매도량 합산'
    )

    # === 비중 및 금액 정보 ===
    trading_weight = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        verbose_name='매매비중',
        help_text='매매비중 (API: trde_wght) - 전체 거래 대비 공매도 비중(%)'
    )
    short_trading_value = models.BigIntegerField(
        verbose_name='공매도거래대금',
        help_text='공매도거래대금 (API: shrts_trde_prica) - 당일 공매도 거래금액'
    )
    short_average_price = models.BigIntegerField(
        verbose_name='공매도평균가',
        help_text='공매도평균가 (API: shrts_avg_pric) - 당일 공매도 평균 체결가'
    )

    # === 메타 정보 ===
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성일시'
    )

    class Meta:
        db_table = 'short_selling'
        verbose_name = '공매도추이'
        verbose_name_plural = '공매도추이'
        ordering = ['-date', 'stock']
        unique_together = [('stock', 'date')]  # 종목+날짜 조합은 유일
        indexes = [
            models.Index(fields=['stock', '-date']),  # 종목별 최신순 조회용
            models.Index(fields=['-date']),           # 날짜별 조회용
        ]

    def __str__(self):
        return f"{self.stock.name} - {self.date} (공매도량: {self.short_volume:,}, 비중: {self.trading_weight}%)"


class Theme(models.Model):
    """
    테마 일별 통계 데이터 (시계열)

    키움 API ka90001 (테마그룹별요청) 응답 데이터 저장
    각 테마의 일자별 등락율, 기간수익률, 종목수 등의 통계를 저장합니다.

    ※ 핵심 개념:
    - 테마는 시장에서 주목받는 테마/섹터를 의미 (예: 2차전지, 반도체, AI 등)
    - 각 테마별로 일자별 통계를 시계열로 저장
    - 같은 테마(code)가 여러 날짜(date)에 대해 여러 레코드를 가짐

    ※ 데이터 구조 예시:
    - Theme(code='TH001', name='2차전지', date='2025-11-29', fluctuation_rate=5.2)
    - Theme(code='TH001', name='2차전지', date='2025-11-28', fluctuation_rate=3.1)
    - Theme(code='TH001', name='2차전지', date='2025-11-27', fluctuation_rate=-1.2)
    → '2차전지' 테마의 3일간 시계열 데이터

    ※ 활용:
    - 테마별 일자별 등락율 추이 차트
    - 테마별 기간수익률 비교
    - 상승/하락 종목수 분석

    ※ 중요:
    - save_theme 명령어를 실행하기 전에 DailyChart 데이터 필수
    - DailyChart에서 실제 거래일을 가져와서 날짜를 매핑
    """

    # === 기본 정보 ===
    code = models.CharField(
        max_length=20,
        verbose_name='테마그룹코드',
        help_text='테마 고유 코드 (API: thema_grp_cd)',
        db_index=True
    )
    name = models.CharField(
        max_length=100,
        verbose_name='테마명',
        help_text='테마 이름 (API: thema_nm) - 예: 2차전지, 반도체, AI 등'
    )
    date = models.DateField(
        verbose_name='일자',
        help_text='거래일자 (DailyChart 기준)',
        db_index=True
    )

    # === 종목 통계 ===
    stock_count = models.IntegerField(
        verbose_name='종목수',
        help_text='종목수 (API: stk_num) - 해당 테마에 속한 종목 개수'
    )
    rising_stock_count = models.IntegerField(
        verbose_name='상승종목수',
        help_text='상승종목수 (API: rising_stk_num) - 당일 상승한 종목 수'
    )
    falling_stock_count = models.IntegerField(
        verbose_name='하락종목수',
        help_text='하락종목수 (API: fall_stk_num) - 당일 하락한 종목 수'
    )

    # === 수익률 정보 ===
    fluctuation_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='등락율',
        help_text='등락율 (API: flu_rt) - 당일 테마 평균 등락율(%)'
    )
    period_profit_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='기간수익률',
        help_text='기간수익률 (API: dt_prft_rt) - 특정 기간 동안의 수익률(%)'
    )

    # === 메타 정보 ===
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성일시'
    )

    class Meta:
        db_table = 'theme'
        verbose_name = '테마통계'
        verbose_name_plural = '테마통계'
        ordering = ['-date', 'code']  # 날짜 최신순, 테마코드순
        unique_together = [('code', 'date')]  # 테마코드+날짜 조합은 유일 (같은 테마의 같은 날짜는 1개만)
        indexes = [
            models.Index(fields=['code', '-date']),  # 테마별 최신순 조회용
            models.Index(fields=['-date']),          # 날짜별 조회용
            models.Index(fields=['-period_profit_rate']),  # 기간수익률 정렬용
        ]

    def __str__(self):
        return f"{self.name}({self.code}) - {self.date} (등락율: {self.fluctuation_rate}%, 수익률: {self.period_profit_rate}%)"


class Sector(models.Model):
    """
    업종별 투자자 순매수 데이터 (시계열)

    키움 API ka10051 (업종별투자자순매수요청) 응답 데이터 저장
    각 업종의 일자별 투자자별(개인/외국인/기관 등) 순매수 데이터를 저장합니다.

    ※ 핵심 개념:
    - 업종은 시장을 세부 분류한 카테고리 (예: 은행, 반도체, 자동차 등)
    - 각 업종별로 일자별 투자자 순매수 통계를 시계열로 저장
    - 코스피/코스닥 시장별로 구분하여 저장

    ※ 데이터 구조 예시:
    - Sector(code='001', name='음식료업', market='KOSPI', date='2025-11-29')
    - Sector(code='001', name='음식료업', market='KOSPI', date='2025-11-28')
    - Sector(code='001', name='음식료업', market='KOSDAQ', date='2025-11-29')
    → 같은 업종도 시장별, 날짜별로 별도 레코드

    ※ 활용:
    - 업종별 투자 주체 분석 (외국인/기관/개인)
    - 업종별 자금 흐름 추이 파악
    - 시장(코스피/코스닥)별 업종 비교

    ※ 중요:
    - save_sector 명령어 실행 전에 DailyChart 데이터 필수
    - mrkt_tp를 0(코스피)과 1(코스닥)로 두 번 호출하여 데이터 수집
    """

    # === 기본 정보 ===
    code = models.CharField(
        max_length=20,
        verbose_name='업종코드',
        help_text='업종 고유 코드 (API: inds_cd)',
        db_index=True
    )
    name = models.CharField(
        max_length=100,
        verbose_name='업종명',
        help_text='업종 이름 (API: inds_nm) - 예: 은행, 반도체, 자동차 등'
    )
    date = models.DateField(
        verbose_name='일자',
        help_text='거래일자 (DailyChart 기준)',
        db_index=True
    )
    market = models.CharField(
        max_length=10,
        choices=[
            ('KOSPI', 'KOSPI'),
            ('KOSDAQ', 'KOSDAQ'),
        ],
        verbose_name='시장구분',
        help_text='코스피(mrkt_tp=0) 또는 코스닥(mrkt_tp=1)',
        db_index=True
    )

    # === 투자자별 순매수 (주요 투자 주체) ===
    individual_net_buying = models.BigIntegerField(
        verbose_name='개인순매수',
        help_text='개인 순매수 (API: ind_netprps) - 양수: 순매수, 음수: 순매도'
    )
    foreign_net_buying = models.BigIntegerField(
        verbose_name='외국인순매수',
        help_text='외국인 순매수 (API: frgnr_netprps)'
    )
    institution_net_buying = models.BigIntegerField(
        verbose_name='기관계순매수',
        help_text='기관계 전체 순매수 (API: orgn_netprps)'
    )

    # === 기관 세부 분류 ===
    securities_net_buying = models.BigIntegerField(
        verbose_name='증권순매수',
        help_text='증권사 순매수 (API: sc_netprps)',
        null=True,
        blank=True
    )
    insurance_net_buying = models.BigIntegerField(
        verbose_name='보험순매수',
        help_text='보험 순매수 (API: insrnc_netprps)',
        null=True,
        blank=True
    )
    investment_trust_net_buying = models.BigIntegerField(
        verbose_name='투신순매수',
        help_text='투신(투자신탁) 순매수 (API: invtrt_netprps)',
        null=True,
        blank=True
    )
    bank_net_buying = models.BigIntegerField(
        verbose_name='은행순매수',
        help_text='은행 순매수 (API: bank_netprps)',
        null=True,
        blank=True
    )
    pension_fund_net_buying = models.BigIntegerField(
        verbose_name='종신금순매수',
        help_text='종신금 순매수 (API: jnsinkm_netprps)',
        null=True,
        blank=True
    )
    endowment_net_buying = models.BigIntegerField(
        verbose_name='기금순매수',
        help_text='기금 순매수 (API: endw_netprps)',
        null=True,
        blank=True
    )
    other_corporation_net_buying = models.BigIntegerField(
        verbose_name='기타법인순매수',
        help_text='기타법인 순매수 (API: etc_corp_netprps)',
        null=True,
        blank=True
    )
    private_fund_net_buying = models.BigIntegerField(
        verbose_name='사모펀드순매수',
        help_text='사모펀드 순매수 (API: samo_fund_netprps)',
        null=True,
        blank=True
    )
    domestic_foreign_net_buying = models.BigIntegerField(
        verbose_name='내국인대우외국인순매수',
        help_text='내국인대우외국인 순매수 (API: native_trmt_frgnr_netprps)',
        null=True,
        blank=True
    )
    nation_net_buying = models.BigIntegerField(
        verbose_name='국가순매수',
        help_text='국가 순매수 (API: natn_netprps)',
        null=True,
        blank=True
    )

    # === 메타 정보 ===
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성일시'
    )

    class Meta:
        db_table = 'sector'
        verbose_name = '업종별순매수'
        verbose_name_plural = '업종별순매수'
        ordering = ['-date', 'market', 'code']
        unique_together = [('code', 'date', 'market')]  # 업종코드+날짜+시장 조합은 유일
        indexes = [
            models.Index(fields=['code', 'market', '-date']),  # 업종+시장별 최신순 조회용
            models.Index(fields=['-date', 'market']),          # 날짜+시장별 조회용
            models.Index(fields=['market', '-date']),          # 시장별 조회용
        ]

    def __str__(self):
        return f"{self.name}({self.code}) [{self.market}] - {self.date} (개인: {self.individual_net_buying:,})"
