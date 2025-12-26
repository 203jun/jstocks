# save_etf_info

네이버 금융에서 ETF 정보(현재가, 등락률, NAV, 시가총액, 구성종목)를 크롤링하여 저장합니다.

## 사용법

```bash
# 전체 관심 ETF 업데이트 (정기 업데이트용)
python manage.py save_etf_info

# 단일 ETF 업데이트
python manage.py save_etf_info --code 305720

# 디버그 모드
python manage.py save_etf_info --log-level debug
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--code` | X | ETF 코드 또는 "all" (기본값: all) |
| `--log-level` | X | 로그 레벨 (debug/info/warning/error, 기본: info) |

## 데이터 소스

- URL: 네이버 금융 (`https://finance.naver.com/item/main.naver?code={code}`)
- 토큰 불필요

## 수집 데이터

| 항목 | 필드명 | 설명 |
|------|--------|------|
| 현재가 | current_price | 현재가 (원) |
| 등락률 | change_rate | 전일대비 등락률 (%) |
| NAV | nav | 순자산가치 (원) |
| 시가총액 | market_cap | 시가총액 (억원) |
| 구성종목 | holdings | 상위 10개 구성종목 (JSON) |

## 저장 모델

- `InfoETF` 모델에 저장
- 기존 데이터 UPDATE (덮어쓰기)

## 출력 예시

```
# 단일 ETF
ETF: KODEX 2차전지산업(305720)
────────────────────────────────────────
결과: 현재가=14,355, 등락률=-1.68%, NAV=14,342, 시총=15,417억, 구성종목=10개

# 전체 ETF
ETF 정보 업데이트 시작 (대상: 2개)
[1/2] 305720 KODEX 2차전지산업: 현재가=14,355, 등락률=-1.68%, NAV=14,342, 시총=15,417억, 구성종목=10개
[2/2] 307520 TIGER 지주회사: 현재가=15,800, 등락률=-2.14%, NAV=15,801, 시총=2,757억, 구성종목=10개
────────────────────────────────────────
완료 | 성공: 2개
```

## 권장 사용법

1. **최초 실행**: ETF 관심종목 저장 시 웹에서 자동으로 저장됨
2. **정기 업데이트**: 일일 업데이트 스크립트에서 실행

```bash
# 일일 정기 업데이트 (daily_update.sh)
python manage.py save_etf_info --log-level info
```

## 주의사항

- `InfoETF` 모델에 ETF가 등록되어 있어야 함 (is_active=True)
- 네이버 API 요청 간격: 0.5초
- 토큰 불필요 (네이버 금융 크롤링)
- `save_etf_chart`와 함께 사용 권장 (차트 + 정보 모두 업데이트)
