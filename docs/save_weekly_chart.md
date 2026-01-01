# save_weekly_chart

키움 API에서 주봉 차트 데이터를 조회하여 저장합니다.

## 사용법

```bash
# 전체 종목, 최근 1주 (정기 업데이트용)
python manage.py save_weekly_chart --code all --mode last

# 전체 종목, 4년치 (최초 1회)
python manage.py save_weekly_chart --code all --mode all

# 단일 종목
python manage.py save_weekly_chart --code 005930 --mode all

# 데이터 삭제
python manage.py save_weekly_chart --clear
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--code` | O* | 종목코드 또는 "all" |
| `--mode` | O* | `all` (4년) / `last` (1주) |
| `--clear` | X | 전체 데이터 삭제 |
| `--log-level` | X | debug / info / warning / error (기본: info) |

\* --clear 사용 시 불필요

## 저장 모델

`WeeklyChart`

## 데이터 소스

- API: 키움 Open API (`ka10082`)
- 토큰 필요

## 수집 데이터

| 항목 | 필드명 |
|------|--------|
| 시가 | opening_price |
| 고가 | high_price |
| 저가 | low_price |
| 종가 | closing_price |
| 전일대비 | price_change |
| 거래량 | trading_volume |
| 거래대금 | trading_value |

## 실행 주기

일 1회 (daily_update.sh)
