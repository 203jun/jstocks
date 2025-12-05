# save_index_chart

지수(KOSPI/KOSDAQ) 일봉 차트 데이터 저장 (네이버 금융)

## 저장 모델

`IndexChart`

## 사용법

```bash
# 전체 지수 (기본값: last 모드)
python manage.py save_index_chart

# 전체 지수, 2024.1.1부터 전체 데이터
python manage.py save_index_chart --mode all

# KOSPI만
python manage.py save_index_chart --code KOSPI

# KOSDAQ만, 전체 데이터
python manage.py save_index_chart --code KOSDAQ --mode all

# 디버그 모드
python manage.py save_index_chart --log-level debug
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--code` | X | 지수코드: KOSPI, KOSDAQ, all (기본값: all) |
| `--mode` | X | `all` (2024.1.1부터) 또는 `last` (마지막 저장일부터, 기본값) |
| `--log-level` | X | 로그 레벨 (debug/info/warning/error, 기본: info) |

## 데이터 소스

네이버 금융 API (fchart.stock.naver.com)

## 수집 데이터

| 항목 | 필드명 | 설명 |
|------|--------|------|
| 시가 | opening_price | 일 시가 |
| 고가 | high_price | 일 고가 |
| 저가 | low_price | 일 저가 |
| 종가 | closing_price | 일 종가 |
| 거래량 | trading_volume | 일 거래량 |

## 실행 주기

일 1회 (장 마감 후)
