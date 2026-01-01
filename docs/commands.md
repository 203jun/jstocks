# 데이터 수집 명령어 총괄

주식 데이터 수집 및 저장을 위한 Django 관리 명령어 목록입니다.

## 명령어 목록 (21개)

| 분류 | 명령어 | 저장 모델 | 데이터 소스 | 실행 주기 |
|------|--------|-----------|-------------|-----------|
| 유틸 | `get_token` | token.json | 키움 API | 일 1회 |
| 유틸 | `check_market_open` | - | 키움 API | 일 1회 |
| 시황 | `save_index_chart` | IndexChart | 네이버 금융 | 일 1회 |
| 시황 | `save_market_trend` | MarketTrend | 네이버 금융 | 일 1회 |
| 업종 | `save_sector` | Sector | 키움 API | 일 1회 |
| 종목 | `save_stock_list` | Info | 키움 API | 수동 |
| 종목 | `save_stock_info` | Info | 키움 API | 일 1회 |
| 종목 | `save_stock_sector` | Info.industry | 키움 API | 수동 |
| 종목 | `save_daily_chart` | DailyChart | 키움 API | 일 1회 |
| 종목 | `save_weekly_chart` | WeeklyChart | 키움 API | 일 1회 |
| 종목 | `save_monthly_chart` | MonthlyChart | 키움 API | 일 1회 |
| 종목 | `save_investor_trend` | InvestorTrend | 키움 API | 일 1회 |
| 종목 | `save_investor_daum` | InvestorTrend | 다음 금융 | 일 1회 |
| 종목 | `save_short_selling` | ShortSelling | 키움 API | 일 1회 |
| 종목 | `save_gongsi_stock` | Gongsi | DART | 일 1회 |
| 종목 | `save_fnguide_report` | Report | FnGuide | 일 1회 |
| 종목 | `save_nodaji_stock` | Nodaji | 네이버 프리미엄 | 일 1회 |
| ETF | `save_etf_chart` | *ChartETF | 네이버 금융 | 일 1회 |
| ETF | `save_etf_info` | InfoETF | 네이버 금융 | 일 1회 |
| 재무 | `save_financial_naver` | Financial | 네이버 금융 | 주 1회 |
| 재무 | `save_init_financial` | Financial | jemu 폴더 | 최초 1회 |

---

## 정기 업데이트

### 일일 (daily_update.sh)

```bash
python manage.py get_token
python manage.py check_market_open || exit 0

# 시황
python manage.py save_index_chart --mode last
python manage.py save_market_trend --mode last

# 종목
python manage.py save_stock_info --code all
python manage.py save_daily_chart --code all --mode last
python manage.py save_weekly_chart --code all --mode last
python manage.py save_monthly_chart --code all --mode last
python manage.py save_sector --mode last

# 관심 종목
python manage.py save_investor_trend --code fav --mode last
python manage.py save_short_selling --code fav --mode last
python manage.py save_gongsi_stock --code fav
python manage.py save_fnguide_report --code fav
python manage.py save_nodaji_stock --code fav

# ETF
python manage.py save_etf_chart --mode last
python manage.py save_etf_info
```

### 다음 금융 수급 (daum_update.sh)

```bash
python manage.py save_investor_daum --code fav --mode last
```

### 주간 (weekly_update.sh)

```bash
python manage.py get_token
python manage.py save_financial_naver --code all
```

---

## 공통 옵션

| 옵션 | 설명 |
|------|------|
| `--code` | 종목코드 / "all" / "fav" |
| `--mode` | `all` (전체) / `last` (최근) |
| `--clear` | 데이터 삭제 |
| `--log-level` | debug / info / warning / error (기본: info) |

### 옵션 필수 여부

| 표시 | 의미 |
|------|------|
| O | 항상 필수 |
| O* | --clear 사용 시 불필요 |
| X | 선택 (기본값 있음) |

---

## 토큰 필요 명령어

**필요:**
- `get_token`, `check_market_open`
- `save_daily_chart`, `save_weekly_chart`, `save_monthly_chart`
- `save_investor_trend`, `save_short_selling`
- `save_sector`, `save_stock_sector`
- `save_stock_info`, `save_stock_list`

**불필요:**
- `save_etf_chart`, `save_etf_info`
- `save_index_chart`, `save_market_trend`
- `save_financial_naver`, `save_investor_daum`
- `save_fnguide_report`, `save_gongsi_stock`, `save_nodaji_stock`
