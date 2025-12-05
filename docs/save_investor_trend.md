# save_investor_trend

투자자별 매매동향 저장 (키움 API ka10059)

## 저장 모델

`InvestorTrend`

## 사용법

```bash
# 특정 종목, 최근 1일
python manage.py save_investor_trend --code 005930 --mode day

# 특정 종목, 6개월
python manage.py save_investor_trend --code 005930 --mode all

# 전체 종목, 최근 1일
python manage.py save_investor_trend --code all --mode day

# 전체 종목, 6개월
python manage.py save_investor_trend --code all --mode all

# 디버그 모드
python manage.py save_investor_trend --code 005930 --mode day --log-level debug
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--code` | O | 종목코드 (예: 005930) 또는 `all` (전체 종목) |
| `--mode` | O | `all` (6개월 데이터) 또는 `day` (최근 거래일 1일만) |
| `--log-level` | X | 로그 레벨 (debug/info/warning/error, 기본: info) |

## 데이터 소스

- API: 키움 Open API (ka10059 - 종목별투자자기관별요청)
- 토큰 필요: `python manage.py get_token` 먼저 실행

## 수집 데이터

| 항목 | 필드명 | 설명 |
|------|--------|------|
| 개인 | individual | 개인 순매수 |
| 외국인 | foreign | 외국인 순매수 |
| 기관계 | institution | 기관 순매수 |
| 국내타법인 | domestic_foreign | 국내타법인 순매수 |
| 금융투자 | financial | 금융투자 순매수 |
| 보험 | insurance | 보험 순매수 |
| 투신 | investment_trust | 투자신탁 순매수 |
| 기타금융 | other_finance | 기타금융 순매수 |
| 은행 | bank | 은행 순매수 |
| 연기금등 | pension_fund | 연기금 순매수 |
| 사모펀드 | private_fund | 사모펀드 순매수 |
| 기타법인 | other_corporation | 기타법인 순매수 |

## 실행 주기

일 1회 (장 마감 후)
