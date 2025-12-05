# save_sector

업종별 투자자 순매수 데이터 저장 (키움 API ka10051)

## 저장 모델

`Sector`

## 사용법

```bash
# 최근 거래일 1일 (기본값)
python manage.py save_sector

# 최근 60거래일
python manage.py save_sector --mode all

# 전체 데이터 삭제
python manage.py save_sector --clear

# 디버그 모드
python manage.py save_sector --mode all --log-level debug
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--mode` | X | `last` (최근 1일, 기본값) 또는 `all` (최근 60거래일) |
| `--clear` | X | 전체 데이터 삭제 |
| `--log-level` | X | 로그 레벨 (debug/info/warning/error, 기본: info) |

## 데이터 소스

- API: 키움 Open API (ka10051 - 업종별투자자순매수요청)
- 토큰 필요: `python manage.py get_token` 먼저 실행

## 수집 데이터

| 항목 | 필드명 | 설명 |
|------|--------|------|
| 업종코드 | code | 업종 코드 |
| 업종명 | name | 업종 이름 |
| 개인 | individual_net_buying | 개인 순매수 |
| 외국인 | foreign_net_buying | 외국인 순매수 |
| 기관계 | institution_net_buying | 기관 순매수 |
| 증권 | securities_net_buying | 증권 순매수 |
| 보험 | insurance_net_buying | 보험 순매수 |
| 투신 | investment_trust_net_buying | 투자신탁 순매수 |
| 은행 | bank_net_buying | 은행 순매수 |
| 연기금등 | pension_fund_net_buying | 연기금 순매수 |
| 기금공제 | endowment_net_buying | 기금공제 순매수 |
| 기타법인 | other_corporation_net_buying | 기타법인 순매수 |
| 사모펀드 | private_fund_net_buying | 사모펀드 순매수 |
| 국내타법인 | domestic_foreign_net_buying | 국내타법인 순매수 |
| 국가 | nation_net_buying | 국가 순매수 |

## 동작 방식

1. DailyChart 테이블에서 거래일 목록 조회
2. 각 거래일에 대해 KOSPI/KOSDAQ 업종별 데이터 수집
3. Sector 테이블에 저장

## 주의사항

- DailyChart 데이터가 있어야 함 (먼저 `save_daily_chart` 실행)
- 토큰 유효성 확인 필요

## 실행 주기

일 1회 (장 마감 후)
