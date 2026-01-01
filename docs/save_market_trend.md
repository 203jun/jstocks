# save_market_trend

네이버 금융에서 시장별 투자자 매매동향을 저장합니다.

## 사용법

```bash
# 전체 시장, 최근 10일 (정기 업데이트용)
python manage.py save_market_trend

# 전체 시장, 60일
python manage.py save_market_trend --mode all

# 특정 시장만
python manage.py save_market_trend --market KOSPI

# 데이터 삭제
python manage.py save_market_trend --clear
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--market` | X | KOSPI / KOSDAQ / FUTURES / all (기본: all) |
| `--mode` | X | `all` (60일) / `last` (10일, 기본) |
| `--clear` | X | 전체 데이터 삭제 |
| `--log-level` | X | debug / info / warning / error (기본: info) |

## 저장 모델

`MarketTrend`

## 데이터 소스

- API: 네이버 금융 (`finance.naver.com`)
- 토큰 불필요

## 수집 데이터

| 항목 | 필드명 |
|------|--------|
| 개인 | individual |
| 외국인 | foreign |
| 기관 | institution |

## 실행 주기

일 1회 (daily_update.sh)
