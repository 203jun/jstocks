# save_financial_naver

네이버 금융에서 재무제표 데이터를 크롤링하여 저장합니다.

## 사용법

```bash
# 전체 종목
python manage.py save_financial_naver --code all

# 단일 종목
python manage.py save_financial_naver --code 005930

# 데이터 삭제
python manage.py save_financial_naver --clear
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--code` | O* | 종목코드 또는 "all" |
| `--clear` | X | 전체 데이터 삭제 |
| `--log-level` | X | debug / info / warning / error (기본: info) |

\* --clear 사용 시 불필요

## 저장 모델

`Financial`

## 데이터 소스

- URL: 네이버 금융 (`finance.naver.com`)
- 토큰 불필요

## 수집 데이터

| 항목 | 필드명 |
|------|--------|
| 매출액 | revenue |
| 영업이익 | operating_profit |
| 당기순이익 | net_income |
| 영업이익률 | operating_margin |
| 순이익률 | net_margin |
| ROE | roe |

## 실행 주기

주 1회 (weekly_update.sh)
