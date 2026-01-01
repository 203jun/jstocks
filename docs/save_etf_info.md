# save_etf_info

네이버 금융에서 ETF 정보를 크롤링하여 저장합니다.

## 사용법

```bash
# 전체 ETF (정기 업데이트용)
python manage.py save_etf_info

# 단일 ETF
python manage.py save_etf_info --etf-code 305720
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--etf-code` | X | ETF 코드 또는 "all" (기본: all) |
| `--log-level` | X | debug / info / warning / error (기본: info) |

## 저장 모델

`InfoETF`

## 데이터 소스

- URL: 네이버 금융 (`finance.naver.com`)
- 토큰 불필요

## 수집 데이터

| 항목 | 필드명 |
|------|--------|
| 현재가 | current_price |
| 등락률 | change_rate |
| NAV | nav |
| 시가총액 | market_cap |
| 구성종목 | holdings |

## 실행 주기

일 1회 (daily_update.sh)
