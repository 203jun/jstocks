from django.db import models


class ThemeCategory(models.Model):
    """
    업종 대분류

    예: 건설/플랜트, 금융/증권, 바이오/제약 등
    """
    name = models.CharField(
        max_length=20,
        unique=True,
        verbose_name='대분류명',
        help_text='업종 대분류 이름 (최대 20자)'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성일시'
    )

    class Meta:
        db_table = 'theme_category'
        verbose_name = '업종 대분류'
        verbose_name_plural = '업종 대분류'
        ordering = ['name']

    def __str__(self):
        return self.name


class Theme(models.Model):
    """
    업종 소분류 (테마)

    예: 도시정비/원전/SMR, 증권사, P-CAB/GLP-1 등
    """
    category = models.ForeignKey(
        ThemeCategory,
        on_delete=models.CASCADE,
        related_name='themes',
        verbose_name='대분류',
        help_text='소속 대분류'
    )
    name = models.CharField(
        max_length=20,
        verbose_name='소분류명',
        help_text='업종 소분류 이름 (최대 20자)'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성일시'
    )

    class Meta:
        db_table = 'theme'
        verbose_name = '업종 소분류'
        verbose_name_plural = '업종 소분류'
        ordering = ['category__name', 'name']
        unique_together = [('category', 'name')]

    def __str__(self):
        return f"{self.category.name} > {self.name}"


class Info(models.Model):
    """
    종목 기본 정보
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
    roe = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='ROE')
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

    # === 업종 관계 ===
    sectors = models.ManyToManyField(
        'Sector',
        related_name='stocks',
        blank=True,
        verbose_name='소속 업종',
        help_text='이 종목이 속한 업종들 (예: 종합, 대형주, 반도체업종 등)'
    )

    # === 관심 단계 ===
    interest_level = models.CharField(
        max_length=10,
        choices=[
            ('super', '초관심'),
            ('normal', '관심'),
            ('incubator', '인큐베이터'),
        ],
        null=True,
        blank=True,
        verbose_name='관심단계',
        help_text='투자 관심 단계 (초관심 > 관심 > 인큐베이터)'
    )
    fav_sync_status = models.CharField(
        max_length=20,
        choices=[
            ('syncing', '동기화 중'),
            ('completed', '완료'),
            ('deleting', '삭제 중'),
        ],
        null=True,
        blank=True,
        verbose_name='관심종목 동기화 상태',
    )

    # === 보유 여부 ===
    is_holding = models.BooleanField(
        default=False,
        verbose_name='보유중',
        help_text='현재 보유 중인 종목 여부'
    )

    # === 사용자 정의 업종 ===
    themes = models.ManyToManyField(
        'Theme',
        related_name='stocks',
        blank=True,
        verbose_name='업종',
        help_text='사용자 정의 업종 (반도체, 전기전력 등)'
    )

    # === 투자 메모 ===
    investment_point = models.TextField(
        blank=True,
        default='',
        verbose_name='투자포인트',
        help_text='투자포인트 (HTML 형식)'
    )
    risk = models.TextField(
        blank=True,
        default='',
        verbose_name='리스크',
        help_text='리스크 (HTML 형식)'
    )
    memo = models.TextField(
        blank=True,
        default='',
        verbose_name='메모',
        help_text='자유 메모 (HTML 형식)'
    )

    class Meta:
        db_table = 'info'
        verbose_name = '종목정보'
        verbose_name_plural = '종목정보'
        ordering = ['code']

    def __str__(self):
        return f"{self.name} ({self.code})"


class InfoETF(models.Model):
    """
    ETF 종목 정보

    네이버 금융에서 크롤링한 ETF 데이터 저장
    일반 종목(Info)과 분리하여 ETF 전용 필드 관리
    """

    # === 기본 정보 ===
    code = models.CharField(
        max_length=10,
        primary_key=True,
        verbose_name='종목코드',
        help_text='ETF 종목코드 (6자리)'
    )
    name = models.CharField(
        max_length=100,
        verbose_name='종목명',
        help_text='ETF 종목명'
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='활성화',
        help_text='활성 상태 여부'
    )

    # === 가격 정보 (네이버 크롤링) ===
    current_price = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name='현재가',
        help_text='현재가 (원)'
    )
    change_rate = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='등락률',
        help_text='전일대비 등락률 (%)'
    )
    nav = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name='NAV',
        help_text='순자산가치 (원)'
    )
    market_cap = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name='시가총액',
        help_text='시가총액 (억원 단위)'
    )

    # === ETF 특성 ===
    management_fee = models.DecimalField(
        max_digits=5,
        decimal_places=3,
        null=True,
        blank=True,
        verbose_name='총보수',
        help_text='총보수 (%, 예: 0.150)'
    )

    # === 구성종목 (JSON) ===
    holdings = models.JSONField(
        default=list,
        blank=True,
        verbose_name='구성종목',
        help_text='구성종목 리스트 [{name, ratio}, ...]'
    )

    # === 메타 정보 ===
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성일시'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='수정일시'
    )

    class Meta:
        db_table = 'info_etf'
        verbose_name = 'ETF 종목정보'
        verbose_name_plural = 'ETF 종목정보'
        ordering = ['-market_cap', 'code']

    def __str__(self):
        return f"{self.name} ({self.code})"


class DailyChartETF(models.Model):
    """
    ETF 일봉 차트 데이터

    네이버 금융 API에서 크롤링한 ETF 일봉 데이터 저장
    """

    etf = models.ForeignKey(
        InfoETF,
        on_delete=models.CASCADE,
        verbose_name='ETF',
        db_index=True
    )
    date = models.DateField(
        verbose_name='일자',
        db_index=True
    )
    opening_price = models.BigIntegerField(verbose_name='시가')
    high_price = models.BigIntegerField(verbose_name='고가')
    low_price = models.BigIntegerField(verbose_name='저가')
    closing_price = models.BigIntegerField(verbose_name='종가')
    trading_volume = models.BigIntegerField(verbose_name='거래량')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='생성일시')

    class Meta:
        db_table = 'daily_chart_etf'
        verbose_name = 'ETF 일봉차트'
        verbose_name_plural = 'ETF 일봉차트'
        ordering = ['-date', 'etf']
        unique_together = [('etf', 'date')]
        indexes = [
            models.Index(fields=['etf', '-date']),
            models.Index(fields=['-date']),
        ]

    def __str__(self):
        return f"{self.etf.name} - {self.date}"


class WeeklyChartETF(models.Model):
    """
    ETF 주봉 차트 데이터

    네이버 금융 API에서 크롤링한 ETF 주봉 데이터 저장
    """

    etf = models.ForeignKey(
        InfoETF,
        on_delete=models.CASCADE,
        verbose_name='ETF',
        db_index=True
    )
    date = models.DateField(
        verbose_name='일자',
        db_index=True
    )
    opening_price = models.BigIntegerField(verbose_name='시가')
    high_price = models.BigIntegerField(verbose_name='고가')
    low_price = models.BigIntegerField(verbose_name='저가')
    closing_price = models.BigIntegerField(verbose_name='종가')
    trading_volume = models.BigIntegerField(verbose_name='거래량')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='생성일시')

    class Meta:
        db_table = 'weekly_chart_etf'
        verbose_name = 'ETF 주봉차트'
        verbose_name_plural = 'ETF 주봉차트'
        ordering = ['-date', 'etf']
        unique_together = [('etf', 'date')]
        indexes = [
            models.Index(fields=['etf', '-date']),
            models.Index(fields=['-date']),
        ]

    def __str__(self):
        return f"{self.etf.name} - {self.date}"


class MonthlyChartETF(models.Model):
    """
    ETF 월봉 차트 데이터

    네이버 금융 API에서 크롤링한 ETF 월봉 데이터 저장
    """

    etf = models.ForeignKey(
        InfoETF,
        on_delete=models.CASCADE,
        verbose_name='ETF',
        db_index=True
    )
    date = models.DateField(
        verbose_name='일자',
        db_index=True
    )
    opening_price = models.BigIntegerField(verbose_name='시가')
    high_price = models.BigIntegerField(verbose_name='고가')
    low_price = models.BigIntegerField(verbose_name='저가')
    closing_price = models.BigIntegerField(verbose_name='종가')
    trading_volume = models.BigIntegerField(verbose_name='거래량')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='생성일시')

    class Meta:
        db_table = 'monthly_chart_etf'
        verbose_name = 'ETF 월봉차트'
        verbose_name_plural = 'ETF 월봉차트'
        ordering = ['-date', 'etf']
        unique_together = [('etf', 'date')]
        indexes = [
            models.Index(fields=['etf', '-date']),
            models.Index(fields=['-date']),
        ]

    def __str__(self):
        return f"{self.etf.name} - {self.date}"


class Financial(models.Model):
    """
    재무제표 데이터 (분기/연간)

    OpenDART 재무정보 일괄다운로드 데이터 저장
    손익계산서/포괄손익계산서에서 추출한 매출액, 영업이익, 순이익 데이터

    ※ 데이터 구분:
    - 분기: quarter 값 있음 (1Q, 2Q, 3Q, 4Q)
    - 연간: quarter = None

    ※ 증가율:
    - 분기: 전분기 대비 증가율
    - 연간: 전년 대비 증가율

    ※ 쿼리 예시:
    - 연간 데이터: Financial.objects.filter(stock=info, quarter__isnull=True)
    - 분기 데이터: Financial.objects.filter(stock=info, quarter__isnull=False)
    - 2024년 전체: Financial.objects.filter(stock=info, year=2024)
    - 2023년 2분기: Financial.objects.filter(stock=info, year=2023, quarter='2Q')
    """

    # === 기본 정보 ===
    stock = models.ForeignKey(
        'Info',
        on_delete=models.CASCADE,
        verbose_name='종목',
        help_text='종목 정보 (Info 모델 참조)',
        db_index=True
    )
    year = models.IntegerField(
        verbose_name='연도',
        help_text='회계연도 (예: 2024)',
        db_index=True
    )
    quarter = models.CharField(
        max_length=2,
        null=True,
        blank=True,
        verbose_name='분기',
        help_text='분기 (1Q, 2Q, 3Q, 4Q) - null이면 연간 데이터',
        db_index=True
    )

    # === 실적 정보 ===
    revenue = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name='매출액',
        help_text='매출액 (원 단위)'
    )
    operating_profit = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name='영업이익',
        help_text='영업이익 (원 단위)'
    )
    net_income = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name='순이익',
        help_text='당기순이익 (원 단위)'
    )

    # === 증가율 (%) ===
    revenue_growth = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='매출액증가율',
        help_text='전분기/전년 대비 매출액 증가율 (%)'
    )
    operating_profit_growth = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='영업이익증가율',
        help_text='전분기/전년 대비 영업이익 증가율 (%)'
    )
    net_income_growth = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='순이익증가율',
        help_text='전분기/전년 대비 순이익 증가율 (%)'
    )

    # === 수익성 지표 (%) ===
    operating_margin = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='영업이익률',
        help_text='영업이익 / 매출액 * 100 (%)'
    )
    net_margin = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='순이익률',
        help_text='당기순이익 / 매출액 * 100 (%)'
    )
    roe = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='ROE',
        help_text='자기자본이익률 (지배주주 기준, %)'
    )

    # === 추정치 여부 ===
    is_estimated = models.BooleanField(
        default=False,
        verbose_name='추정치여부',
        help_text='네이버 금융 (E) 표시 - True면 추정치'
    )

    # === 메타 정보 ===
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성일시'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='수정일시'
    )

    class Meta:
        db_table = 'financial'
        verbose_name = '재무제표'
        verbose_name_plural = '재무제표'
        ordering = ['-year', '-quarter']
        unique_together = [('stock', 'year', 'quarter')]
        indexes = [
            models.Index(fields=['stock', '-year', '-quarter']),  # 종목별 최신순 조회용
            models.Index(fields=['-year', '-quarter']),           # 연도/분기별 조회용
        ]

    def __str__(self):
        period = f"{self.year} {self.quarter}" if self.quarter else f"{self.year}"
        return f"{self.stock.name} - {period}"


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


class Report(models.Model):
    """
    애널리스트 리포트 데이터

    FnGuide API (comp.wisereport.co.kr) 응답 데이터 저장
    각 종목의 증권사 애널리스트 리포트 정보를 저장합니다.

    ※ 핵심 정보:
    - 리포트 제목, 작성자(애널리스트), 제공처(증권사)
    - 목표가, 투자의견 (BUY, HOLD, SELL 등)
    - 발행일

    ※ 활용:
    - 종목별 최신 리포트 조회
    - 목표가 추이 분석
    - 증권사별 투자의견 비교
    """

    # === 기본 정보 ===
    stock = models.ForeignKey(
        Info,
        on_delete=models.CASCADE,
        verbose_name='종목',
        help_text='종목 정보 (Info 모델 참조)',
        db_index=True
    )
    report_id = models.IntegerField(
        verbose_name='리포트ID',
        help_text='FnGuide 리포트 고유 ID (API: RPT_ID)',
        unique=True
    )
    date = models.DateField(
        verbose_name='발행일',
        help_text='리포트 발행일 (API: ANL_DT)',
        db_index=True
    )

    # === 리포트 정보 ===
    title = models.CharField(
        max_length=500,
        verbose_name='제목',
        help_text='리포트 제목 (API: RPT_TITLE)'
    )
    author = models.CharField(
        max_length=100,
        verbose_name='작성자',
        help_text='애널리스트명 (API: ANL_NM_KOR) - 복수인 경우 콤마로 구분'
    )
    provider = models.CharField(
        max_length=100,
        verbose_name='제공처',
        help_text='증권사명 (API: BRK_NM_KOR)'
    )

    # === 투자의견 ===
    target_price = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name='목표가',
        help_text='목표주가 (API: TARGET_PRC) - 없는 경우 null'
    )
    recommendation = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        verbose_name='투자의견',
        help_text='투자의견 (API: RECOMM) - BUY, HOLD, SELL 등'
    )

    # === 메타 정보 ===
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성일시'
    )

    class Meta:
        db_table = 'report'
        verbose_name = '애널리스트리포트'
        verbose_name_plural = '애널리스트리포트'
        ordering = ['-date', 'stock']
        indexes = [
            models.Index(fields=['stock', '-date']),  # 종목별 최신순 조회용
            models.Index(fields=['-date']),           # 날짜별 조회용
        ]

    def __str__(self):
        target = f"{self.target_price:,}원" if self.target_price else "-"
        return f"{self.stock.name} - {self.date} [{self.provider}] {self.title[:30]} (목표가: {target})"


class Nodaji(models.Model):
    """
    노다지 IR노트 기사 데이터

    네이버 프리미엄 콘텐츠 '노다지 IR노트' 검색 결과 저장
    https://contents.premium.naver.com/ystreet/irnote

    ※ 활용:
    - 종목별 노다지 기사 조회
    - IR 분석 자료 아카이빙
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
        null=True,
        blank=True,
        verbose_name='발행일',
        help_text='기사 발행일',
        db_index=True
    )

    # === 기사 정보 ===
    title = models.CharField(
        max_length=500,
        verbose_name='제목',
        help_text='기사 제목'
    )
    link = models.URLField(
        max_length=500,
        verbose_name='링크',
        help_text='기사 URL'
    )
    summary = models.TextField(
        blank=True,
        verbose_name='요약',
        help_text='기사 요약 내용'
    )

    # === 메타 정보 ===
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성일시'
    )

    class Meta:
        db_table = 'nodaji'
        verbose_name = '노다지기사'
        verbose_name_plural = '노다지기사'
        ordering = ['-date', 'stock']
        indexes = [
            models.Index(fields=['stock', '-date']),  # 종목별 최신순 조회용
            models.Index(fields=['-date']),           # 날짜별 조회용
        ]

    def __str__(self):
        return f"{self.stock.name} - {self.date} {self.title[:30]}"


class Gongsi(models.Model):
    """
    DART 공시 데이터

    전자공시시스템(DART)에서 가져온 공시 정보 저장
    https://dart.fss.or.kr

    ※ 활용:
    - 종목별 공시 조회
    - 주요 공시 아카이빙
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
        null=True,
        blank=True,
        verbose_name='접수일',
        help_text='공시 접수일',
        db_index=True
    )

    # === 공시 정보 ===
    title = models.CharField(
        max_length=500,
        verbose_name='보고서명',
        help_text='공시 보고서명'
    )
    link = models.URLField(
        max_length=500,
        verbose_name='링크',
        help_text='DART 공시 URL'
    )
    submitter = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='제출인',
        help_text='공시 제출인'
    )

    # === 메타 정보 ===
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성일시'
    )

    class Meta:
        db_table = 'gongsi'
        verbose_name = '공시'
        verbose_name_plural = '공시'
        ordering = ['-date', 'stock']
        indexes = [
            models.Index(fields=['stock', '-date']),  # 종목별 최신순 조회용
            models.Index(fields=['-date']),           # 날짜별 조회용
        ]

    def __str__(self):
        return f"{self.stock.name} - {self.date} {self.title[:30]}"


class Schedule(models.Model):
    """
    종목별 일정 정보

    ※ 구조:
    - date_text: 표시용 날짜 텍스트 ("내년 상반기", "2025-03-15" 등)
    - date_sort: 정렬/알림용 날짜 (대략적인 날짜, 선택사항)
    - content: 일정 내용
    """

    # === 기본 정보 ===
    stock = models.ForeignKey(
        Info,
        on_delete=models.CASCADE,
        related_name='schedules',
        verbose_name='종목',
        db_index=True
    )
    date_text = models.CharField(
        max_length=50,
        verbose_name='날짜(표시)',
        help_text='표시용 날짜 텍스트 (예: "내년 상반기", "2025-03-15")'
    )
    date_sort = models.DateField(
        null=True,
        blank=True,
        verbose_name='알림일자',
        help_text='정렬/알림용 날짜 (대략적인 날짜, 선택사항)',
        db_index=True
    )
    content = models.CharField(
        max_length=200,
        verbose_name='내용',
        help_text='일정 내용'
    )

    # === 메타 정보 ===
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성일시'
    )

    class Meta:
        db_table = 'schedule'
        verbose_name = '일정'
        verbose_name_plural = '일정'
        ordering = ['date_sort', 'stock']
        indexes = [
            models.Index(fields=['stock', 'date_sort']),
            models.Index(fields=['date_sort']),
        ]

    def __str__(self):
        return f"{self.stock.name} - {self.date_text} {self.content[:20]}"


class IndexChart(models.Model):
    """
    지수 일봉 차트 데이터 (KOSPI, KOSDAQ)

    ※ 데이터 소스: 네이버 금융 API
    - https://fchart.stock.naver.com/siseJson.nhn?symbol={code}&requestType=1&startTime={start}&endTime={end}&timeframe=day
    """

    # === 기본 정보 ===
    code = models.CharField(
        max_length=10,
        verbose_name='지수코드',
        help_text='지수 코드 (KOSPI, KOSDAQ)',
        db_index=True
    )
    date = models.DateField(
        verbose_name='일자',
        db_index=True
    )

    # === 가격 정보 (OHLC) ===
    opening_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='시가'
    )
    high_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='고가'
    )
    low_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='저가'
    )
    closing_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='종가'
    )

    # === 거래 정보 ===
    trading_volume = models.BigIntegerField(
        verbose_name='거래량'
    )

    # === 메타 정보 ===
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성일시'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='수정일시'
    )

    class Meta:
        db_table = 'index_chart'
        verbose_name = '지수차트'
        verbose_name_plural = '지수차트'
        ordering = ['-date', 'code']
        unique_together = [('code', 'date')]
        indexes = [
            models.Index(fields=['code', '-date']),
            models.Index(fields=['-date']),
        ]

    def __str__(self):
        return f"{self.code} - {self.date}"


class MarketTrend(models.Model):
    """
    시장별 투자자 매매동향 (KOSPI, KOSDAQ, FUTURES)

    네이버 금융 투자자별 매매동향 데이터 저장
    https://finance.naver.com/sise/sise_trans_style.naver?sosok=01

    ※ 시장 코드:
    - 01: KOSPI
    - 02: KOSDAQ
    - 03: FUTURES (선물)
    """

    # === 기본 정보 ===
    market = models.CharField(
        max_length=10,
        verbose_name='시장',
        help_text='KOSPI, KOSDAQ, FUTURES',
        db_index=True
    )
    date = models.DateField(
        verbose_name='일자',
        db_index=True
    )

    # === 주요 투자자 ===
    individual = models.BigIntegerField(
        verbose_name='개인',
        help_text='개인 순매수 (백만원)'
    )
    foreign = models.BigIntegerField(
        verbose_name='외국인',
        help_text='외국인 순매수 (백만원)'
    )
    institution = models.BigIntegerField(
        verbose_name='기관계',
        help_text='기관 전체 순매수 (백만원)'
    )

    # === 기관 세부 ===
    financial_investment = models.BigIntegerField(
        verbose_name='금융투자',
        help_text='금융투자 순매수 (백만원)',
        null=True,
        blank=True
    )
    insurance = models.BigIntegerField(
        verbose_name='보험',
        help_text='보험 순매수 (백만원)',
        null=True,
        blank=True
    )
    trust = models.BigIntegerField(
        verbose_name='투신(사모)',
        help_text='투신/사모 순매수 (백만원)',
        null=True,
        blank=True
    )
    bank = models.BigIntegerField(
        verbose_name='은행',
        help_text='은행 순매수 (백만원)',
        null=True,
        blank=True
    )
    other_financial = models.BigIntegerField(
        verbose_name='기타금융기관',
        help_text='기타금융기관 순매수 (백만원)',
        null=True,
        blank=True
    )
    pension_fund = models.BigIntegerField(
        verbose_name='연기금등',
        help_text='연기금 등 순매수 (백만원)',
        null=True,
        blank=True
    )
    other_corporation = models.BigIntegerField(
        verbose_name='기타법인',
        help_text='기타법인 순매수 (백만원)',
        null=True,
        blank=True
    )

    # === 메타 정보 ===
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성일시'
    )

    class Meta:
        db_table = 'market_trend'
        verbose_name = '시장별매매동향'
        verbose_name_plural = '시장별매매동향'
        ordering = ['-date', 'market']
        unique_together = [('market', 'date')]
        indexes = [
            models.Index(fields=['market', '-date']),
            models.Index(fields=['-date']),
        ]

    def __str__(self):
        return f"{self.market} - {self.date} (개인: {self.individual:,}, 외국인: {self.foreign:,})"




class ExcludedYoutubeChannel(models.Model):
    """
    유튜브 검색 제외 채널

    유튜브 검색 시 해당 채널의 영상을 결과에서 제외
    """

    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name='채널명',
        help_text='제외할 유튜브 채널명'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='등록일시'
    )

    class Meta:
        db_table = 'excluded_youtube_channel'
        verbose_name = '유튜브 제외 채널'
        verbose_name_plural = '유튜브 제외 채널'
        ordering = ['name']

    def __str__(self):
        return self.name


class PreferredYoutubeChannel(models.Model):
    """
    유튜브 선호 채널

    선호 모드 검색 시 해당 채널에서만 검색
    """

    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name='채널명',
        help_text='선호 유튜브 채널명'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='등록일시'
    )

    class Meta:
        db_table = 'preferred_youtube_channel'
        verbose_name = '유튜브 선호 채널'
        verbose_name_plural = '유튜브 선호 채널'
        ordering = ['name']

    def __str__(self):
        return self.name


class YoutubeVideo(models.Model):
    """
    저장된 유튜브 영상

    종목별로 관심 영상을 저장
    """

    stock = models.ForeignKey(
        Info,
        on_delete=models.CASCADE,
        related_name='youtube_videos',
        verbose_name='종목'
    )
    video_id = models.CharField(
        max_length=20,
        verbose_name='영상ID',
        help_text='유튜브 영상 고유 ID'
    )
    title = models.CharField(
        max_length=200,
        verbose_name='제목'
    )
    channel = models.CharField(
        max_length=100,
        verbose_name='채널명'
    )
    thumbnail = models.URLField(
        max_length=500,
        blank=True,
        verbose_name='썸네일'
    )
    duration = models.CharField(
        max_length=20,
        blank=True,
        verbose_name='재생시간'
    )
    views = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='조회수'
    )
    published = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='업로드일'
    )
    summary = models.TextField(
        blank=True,
        verbose_name='요약',
        help_text='영상 요약 내용'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='저장일시'
    )

    class Meta:
        db_table = 'youtube_video'
        verbose_name = '유튜브 영상'
        verbose_name_plural = '유튜브 영상'
        ordering = ['-created_at']
        unique_together = [('stock', 'video_id')]

    def __str__(self):
        return f"{self.stock.name} - {self.title}"

    @property
    def link(self):
        return f'https://www.youtube.com/watch?v={self.video_id}'


class SystemSetting(models.Model):
    """
    시스템 설정 (키-값 저장)

    프롬프트, 설정값 등을 저장하는 범용 설정 테이블
    """
    key = models.CharField(
        max_length=100,
        unique=True,
        primary_key=True,
        verbose_name='설정키'
    )
    value = models.TextField(
        blank=True,
        verbose_name='설정값'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='수정일시'
    )

    class Meta:
        db_table = 'system_setting'
        verbose_name = '시스템 설정'
        verbose_name_plural = '시스템 설정'

    def __str__(self):
        return self.key
