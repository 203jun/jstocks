# save_investor_trend

키움 API에서 투자자별 매매동향을 저장합니다.

## 사용법

```bash
# 관심 종목, 최근 1일 (정기 업데이트용)
python manage.py save_investor_trend --code fav --mode last

# 전체 종목, 6개월
python manage.py save_investor_trend --code all --mode all

# 단일 종목
python manage.py save_investor_trend --code 005930 --mode all

# 데이터 삭제
python manage.py save_investor_trend --clear
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--code` | O* | 종목코드 / "all" / "fav" |
| `--mode` | O* | `all` (6개월) / `last` (1일) |
| `--clear` | X | 데이터 삭제 |
| `--log-level` | X | debug / info / warning / error (기본: info) |

\* --clear 사용 시 불필요

## 저장 모델

`InvestorTrend`

## 데이터 소스

- API: 키움 Open API (`ka10059`)
- 토큰 필요

## 수집 데이터

| 항목 | 필드명 |
|------|--------|
| 개인 | individual |
| 외국인 | foreign |
| 기관 | institution |
| 금융투자 | financial |
| 보험 | insurance |
| 투신 | investment_trust |
| 은행 | bank |
| 연기금 | pension_fund |

## 실행 주기

일 1회 (daily_update.sh)
