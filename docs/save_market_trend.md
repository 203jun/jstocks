# save_market_trend

시장별 투자자 매매동향 저장 (네이버 금융)

## 저장 모델

`MarketTrend`

## 사용법

```bash
# 전체 시장, 최근 1페이지 (10일)
python manage.py save_market_trend

# 전체 시장, 6페이지 (60일)
python manage.py save_market_trend --mode all

# KOSPI만
python manage.py save_market_trend --market KOSPI

# KOSDAQ만, 전체 데이터
python manage.py save_market_trend --market KOSDAQ --mode all

# 선물시장
python manage.py save_market_trend --market FUTURES

# 디버그 모드
python manage.py save_market_trend --log-level debug
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--market` | X | 시장: KOSPI, KOSDAQ, FUTURES, all (기본값: all) |
| `--mode` | X | `all` (6페이지, 60일) 또는 `day` (1페이지, 10일, 기본값) |
| `--log-level` | X | 로그 레벨 (debug/info/warning/error, 기본: info) |

## 데이터 소스

네이버 금융 (investorDealTrendDay)

## 수집 데이터

| 항목 | 필드명 | 설명 |
|------|--------|------|
| 개인 | individual | 개인 순매수 |
| 외국인 | foreign | 외국인 순매수 |
| 기관계 | institution | 기관 순매수 |
| 금융투자 | financial_investment | 금융투자 순매수 |
| 보험 | insurance | 보험 순매수 |
| 투신 | trust | 투자신탁 순매수 |
| 은행 | bank | 은행 순매수 |
| 기타금융 | other_financial | 기타금융 순매수 |
| 연기금등 | pension_fund | 연기금 순매수 |
| 기타법인 | other_corporation | 기타법인 순매수 |

## 실행 주기

일 1회 (장 마감 후)
