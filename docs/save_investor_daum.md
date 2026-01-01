# save_investor_daum

다음 금융 투자자별 매매동향 저장 (외국인/기관 순매수량)

## 사용법

```bash
# 단일 종목, 최근 1일
python manage.py save_investor_daum --code 005930 --mode last

# 단일 종목, 최근 60일
python manage.py save_investor_daum --code 005930 --mode all

# 전체 종목, 최근 1일
python manage.py save_investor_daum --code all --mode last

# 관심 종목만, 최근 1일
python manage.py save_investor_daum --code fav --mode last
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--code` | O | 종목코드 또는 "all" / "fav" |
| `--mode` | O | `all` (최근 60일) 또는 `last` (최근 1일) |
| `--log-level` | X | 로그 레벨 (debug/info/warning/error, 기본: info) |

## 저장 모델

`InvestorTrend` (daum_foreign, daum_institution 필드)

## 데이터 소스

- API: 다음 금융 (`https://finance.daum.net/api/investor/days`)
- 토큰 불필요

## 수집 데이터

| 항목 | 필드명 | 설명 |
|------|--------|------|
| 외국인 순매수 | daum_foreign | 외국인 순매수량 |
| 기관 순매수 | daum_institution | 기관 순매수량 |

## 실행 주기

일 1회 (daum_update.sh)

## 주의사항

- `save_investor_trend`와 병행 사용 (키움 데이터와 다음 데이터 모두 저장)
- 기존 InvestorTrend 레코드가 있으면 daum 필드만 업데이트
