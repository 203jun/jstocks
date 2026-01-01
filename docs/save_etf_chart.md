# save_etf_chart

네이버 금융 API에서 ETF 차트 데이터(일봉, 주봉, 월봉)를 조회하여 저장합니다.

## 사용법

```bash
# 전체 ETF, 최근 데이터 (정기 업데이트용)
python manage.py save_etf_chart

# 전체 ETF, 전체 기간
python manage.py save_etf_chart --mode all

# 단일 ETF
python manage.py save_etf_chart --etf-code 305720 --mode all

# 데이터 삭제
python manage.py save_etf_chart --clear
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--etf-code` | X | ETF 코드 또는 "all" (기본: all) |
| `--mode` | X | `all` (전체) / `last` (최근, 기본) |
| `--clear` | X | 전체 데이터 삭제 |
| `--log-level` | X | debug / info / warning / error (기본: info) |

## 저장 모델

`DailyChartETF`, `WeeklyChartETF`, `MonthlyChartETF`

## 데이터 소스

- API: 네이버 금융 (`api.finance.naver.com`)
- 토큰 불필요

## 수집 범위

| 타임프레임 | all 모드 | last 모드 |
|------------|----------|-----------|
| 일봉 | 2년 | 30일 |
| 주봉 | 4년 | 12주 |
| 월봉 | 6년 | 12개월 |

## 실행 주기

일 1회 (daily_update.sh)
