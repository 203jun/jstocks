# save_index_chart

네이버 금융에서 지수(KOSPI/KOSDAQ) 일봉 차트를 저장합니다.

## 사용법

```bash
# 전체 지수, 최근 데이터 (정기 업데이트용)
python manage.py save_index_chart

# 전체 지수, 2024.1.1부터
python manage.py save_index_chart --mode all

# 특정 지수만
python manage.py save_index_chart --market KOSPI

# 데이터 삭제
python manage.py save_index_chart --clear
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--market` | X | KOSPI / KOSDAQ / all (기본: all) |
| `--mode` | X | `all` (2024.1.1~) / `last` (마지막 저장일~, 기본) |
| `--clear` | X | 전체 데이터 삭제 |
| `--log-level` | X | debug / info / warning / error (기본: info) |

## 저장 모델

`IndexChart`

## 데이터 소스

- API: 네이버 금융 (`fchart.stock.naver.com`)
- 토큰 불필요

## 수집 데이터

| 항목 | 필드명 |
|------|--------|
| 시가 | opening_price |
| 고가 | high_price |
| 저가 | low_price |
| 종가 | closing_price |
| 거래량 | trading_volume |

## 실행 주기

일 1회 (daily_update.sh)
