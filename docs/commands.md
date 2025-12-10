# 데이터 수집 명령어 총괄

주식 데이터 수집 및 저장을 위한 Django 관리 명령어 목록입니다.

## 명령어 목록 (17개)

| 분류 | 명령어 | 저장 모델 | 데이터 소스 | 실행 주기 |
|------|--------|-----------|-------------|-----------|
| 시황 | `save_index_chart` | IndexChart | 네이버 금융 | 일 1회 |
| 시황 | `save_market_trend` | MarketTrend | 네이버 금융 | 일 1회 |
| 업종 | `save_sector` | Sector | 키움 API (ka10051) | 일 1회 |
| 종목 | `save_daily_chart` | DailyChart | 키움 API (ka10081) | 일 1회 |
| 종목 | `save_weekly_chart` | WeeklyChart | 키움 API (ka10082) | 일 1회 |
| 종목 | `save_monthly_chart` | MonthlyChart | 키움 API (ka10083) | 일 1회 |
| 종목 | `save_investor_trend` | InvestorTrend | 키움 API (ka10059) | 일 1회 |
| 종목 | `save_short_selling` | ShortSelling | 키움 API (ka10014) | 일 1회 |
| 종목 | `save_gongsi_stock` | Gongsi | DART 전자공시 | 일 1회 |
| 종목 | `save_fnguide_report` | Report | FnGuide | 일 1회 |
| 종목 | `save_nodaji_stock` | Nodaji | 네이버 프리미엄 | 일 1회 |
| 종목 | `save_stock_list` | Info | 키움 API (ka10099) | 주 1회 |
| 종목 | `save_stock_info` | Info | 키움 API (ka10001) | 일 1회 |
| 종목 | `save_stock_sector` | Info.sectors (M2M) | 키움 API (ka20002) | 주 1회 |
| ETF | `save_etf_chart` | DailyChartETF, WeeklyChartETF, MonthlyChartETF | 네이버 금융 | 일 1회 |
| 재무 | `save_financial_naver` | Financial | 네이버 금융 | 주 1회 |
| 재무 | `save_init_financial` | Financial | OpenDART (jemu 폴더) | 최초 1회 |

---

## 최초 실행 (1회)

처음 데이터를 구축할 때 실행합니다.

### 0. 토큰 발급 (필수)

```bash
python manage.py get_token
```

### 1. 종목 기본 정보

```bash
python manage.py save_stock_list --log-level info
python manage.py save_stock_info --code all --log-level info
```

### 2. 시황 데이터 (전체)

```bash
python manage.py save_index_chart --mode all --log-level info
python manage.py save_market_trend --mode all --log-level info
```

### 3. 차트 데이터 (전체)

```bash
python manage.py save_daily_chart --code all --mode all --log-level info
python manage.py save_weekly_chart --code all --mode all --log-level info
python manage.py save_monthly_chart --code all --mode all --log-level info
```

### 4. 재무제표

```bash
python manage.py save_init_financial --code all --log-level info
python manage.py save_financial_naver --code all --log-level info
```

### 5. 업종 데이터

```bash
python manage.py save_sector --mode all --log-level info
python manage.py save_stock_sector --log-level info
```

---

## 정기 업데이트

### 일 1회

장 마감 후 실행합니다. (`daily_update.sh` 스크립트 사용)

```bash
# 토큰 발급 (키움 API 사용 전 필수)
python manage.py get_token

# 시황
python manage.py save_index_chart --mode last --log-level info
python manage.py save_market_trend --mode last --log-level info

# 종목 기본정보
python manage.py save_stock_info --code all --log-level info

# 종목 차트
python manage.py save_daily_chart --code all --mode last --log-level info
python manage.py save_weekly_chart --code all --mode last --log-level info
python manage.py save_monthly_chart --code all --mode last --log-level info

# 업종 (일봉 차트 이후 실행)
python manage.py save_sector --mode last --log-level info

# 종목 수급 (관심 종목만)
python manage.py save_investor_trend --code fav --mode last --log-level info
python manage.py save_short_selling --code fav --mode last --log-level info

# 종목 뉴스 (관심 종목만)
python manage.py save_gongsi_stock --code fav --log-level info
python manage.py save_fnguide_report --code fav --log-level info
python manage.py save_nodaji_stock --code fav --log-level info

# ETF 차트
python manage.py save_etf_chart --mode last --log-level info
```

### 주 1회

주말에 실행합니다. (`weekly_update.sh` 스크립트 사용)

```bash
# 토큰 발급 (키움 API 사용 전 필수)
python manage.py get_token

python manage.py save_stock_list --log-level info
python manage.py save_stock_sector --log-level info
python manage.py save_financial_naver --code all --log-level info
```

---

## 크론잡 설정

웹 UI 설정 페이지에서 크론잡을 등록하거나, 시스템 crontab을 사용합니다.

### Django 크론잡 (권장)

설정 페이지에서 등록 후, 서버 crontab에 아래 추가:

```bash
# 매분 실행 - Django 크론잡 스케줄러
* * * * * cd /home/stock/jstocks && /home/stock/jstocks/venv/bin/python manage.py run_cron >> /home/stock/jstocks/logs/cron.log 2>&1
```

**예시 설정:**

| 작업명 | 유형 | 명령어 | 시간 | 요일 |
|--------|------|--------|------|------|
| 일일 업데이트 | 스크립트 | `daily_update.sh` | 16:00 | 월~금 |
| 수급 추가 수집 | 명령어 | `save_investor_trend --code fav --mode last` | 19:00 | 월~금 |
| 주간 업데이트 | 스크립트 | `weekly_update.sh` | 10:00 | 토 |

### 시스템 crontab 직접 사용

```bash
# 일일 업데이트 (평일 16:00)
0 16 * * 1-5 /home/stock/jstocks/daily_update.sh >> /home/stock/jstocks/logs/daily_update.log 2>&1

# 주간 업데이트 (토요일 10:00)
0 10 * * 6 /home/stock/jstocks/weekly_update.sh >> /home/stock/jstocks/logs/weekly_update.log 2>&1
```

---

## 공통 옵션

| 옵션 | 설명 |
|------|------|
| `--log-level` | 로그 레벨 (debug/info/warning/error, 기본: info) |
| `--clear` | 데이터 삭제 (단독: 전체, `--code`와 조합: 해당 종목만) |

### --code 옵션 값

일부 명령어는 `--code` 옵션에 특수 값을 지원합니다:

| 값 | 설명 | 지원 명령어 |
|----|------|-------------|
| `all` | 전체 종목 | 대부분의 종목별 명령어 |
| `fav` | 관심 종목만 (interest_level 설정된 종목) | `save_investor_trend`, `save_short_selling`, `save_gongsi_stock`, `save_fnguide_report`, `save_nodaji_stock` |

```bash
# 관심 종목만 처리 (초관심/관심/인큐베이터)
python manage.py save_investor_trend --code fav --mode last
python manage.py save_short_selling --code fav --mode last
python manage.py save_gongsi_stock --code fav
python manage.py save_fnguide_report --code fav
python manage.py save_nodaji_stock --code fav
```

---

## 관심 종목 변경 시

### 새 관심 종목 등록

종목을 관심으로 등록한 후 초기 데이터를 수집합니다:

```bash
# 예시: 005930 종목을 관심으로 등록한 경우

# 수급 데이터 (전체 기간)
python manage.py save_investor_trend --code 005930 --mode all --log-level info
python manage.py save_short_selling --code 005930 --mode all --log-level info

# 뉴스/공시/리포트
python manage.py save_gongsi_stock --code 005930 --log-level info
python manage.py save_fnguide_report --code 005930 --log-level info
python manage.py save_nodaji_stock --code 005930 --log-level info
```

### 관심 종목 해제

종목을 관심에서 해제한 후 데이터를 삭제합니다:

```bash
# 예시: 005930 종목을 관심에서 해제한 경우

python manage.py save_investor_trend --clear --code 005930
python manage.py save_short_selling --clear --code 005930
python manage.py save_gongsi_stock --clear --code 005930
python manage.py save_fnguide_report --clear --code 005930
python manage.py save_nodaji_stock --clear --code 005930
```

---

## 데이터 삭제 (--clear)

```bash
# 시황
python manage.py save_index_chart --clear
python manage.py save_market_trend --clear

# 업종
python manage.py save_sector --clear
python manage.py save_stock_sector --clear

# 차트
python manage.py save_daily_chart --clear
python manage.py save_weekly_chart --clear
python manage.py save_monthly_chart --clear

# ETF 차트
python manage.py save_etf_chart --clear

# 수급
python manage.py save_investor_trend --clear
python manage.py save_short_selling --clear

# 뉴스
python manage.py save_gongsi_stock --clear
python manage.py save_fnguide_report --clear
python manage.py save_nodaji_stock --clear

# 재무제표
python manage.py save_financial_naver --clear
python manage.py save_init_financial --clear

# 종목 (주의: 연결된 모든 데이터 삭제됨)
python manage.py save_stock_list --clear
```

**주의:** `save_stock_info`는 `--clear` 옵션이 없습니다.

---

## 토큰 필요 명령어

키움 API를 사용하는 명령어는 토큰이 필요합니다:

```bash
python manage.py get_token
```

토큰 필요:
- `save_daily_chart`, `save_weekly_chart`, `save_monthly_chart`
- `save_investor_trend`, `save_short_selling`
- `save_sector`, `save_stock_sector`
- `save_stock_info`, `save_stock_list`

토큰 불필요 (네이버 금융 API 사용):
- `save_etf_chart`
- `save_index_chart`, `save_market_trend`
- `save_financial_naver`

---

## 로그 스타일 가이드

모든 save_* 명령어는 통일된 로그 스타일을 사용합니다.

### 시작 메시지

```
{명령어} 저장 시작 (모드: {mode}, 대상: {total}개 종목)
종목: {name}({code}) | 모드: {mode}
```

### 진행 상황

```
[{idx}/{total}] {code} {name}: 신규 {n}건, 업데이트 {m}건
```

### 완료 메시지

```
완료 | 성공: {n}개, 데이터없음: {m}개, 오류: {k}개

[오류 목록]
  {code} {name}: {error_message}
```

### 예시

```
$ python manage.py save_daily_chart --code all --mode last --log-level info

일봉 차트 저장 시작 (모드: last, 대상: 2,500개 종목)
────────────────────────────────────────
[1/2500] 005930 삼성전자: 신규 1건
[2/2500] 000660 SK하이닉스: 신규 1건
...
────────────────────────────────────────
완료 | 성공: 2,498개, 데이터없음: 2개
```
