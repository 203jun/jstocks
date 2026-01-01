# save_stock_info

키움 API에서 종목 기본정보를 조회하여 저장합니다.

## 사용법

```bash
# 전체 종목 (정기 업데이트용)
python manage.py save_stock_info --code all

# 단일 종목
python manage.py save_stock_info --code 005930

# 최소 시가총액 변경 (500억 미만 비활성화)
python manage.py save_stock_info --code all --min-cap 500
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--code` | O | 종목코드 또는 "all" |
| `--min-cap` | X | 최소 시가총액 (억, 기본: 1000) |
| `--log-level` | X | debug / info / warning / error (기본: info) |

## 저장 모델

`Info`

## 데이터 소스

- API: 키움 Open API (`ka10001`)
- 토큰 필요

## 수집 데이터

| 항목 | 필드명 |
|------|--------|
| 현재가 | current_price |
| 전일대비 | price_change |
| 등락률 | change_rate |
| 시가총액 | market_cap |
| 거래량 | trading_volume |
| 52주 최고 | high_52w |
| 52주 최저 | low_52w |
| PER | per |
| PBR | pbr |

## 실행 주기

일 1회 (daily_update.sh)
