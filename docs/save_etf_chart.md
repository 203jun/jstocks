# save_etf_chart

네이버 금융 API에서 ETF 차트 데이터(일봉, 주봉, 월봉)를 조회하여 저장합니다.

## 사용법

```bash
# 전체 ETF, 최근 데이터만 (정기 업데이트용)
python manage.py save_etf_chart

# 전체 ETF, 전체 기간
python manage.py save_etf_chart --mode all

# 단일 ETF, 전체 기간 (최초 1회)
python manage.py save_etf_chart --code 305720 --mode all

# 단일 ETF, 최근 데이터만
python manage.py save_etf_chart --code 305720 --mode last

# 데이터 삭제
python manage.py save_etf_chart --clear

# 디버그 모드
python manage.py save_etf_chart --code 305720 --mode all --log-level debug
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--code` | X | ETF 코드 또는 "all" (기본값: all) |
| `--mode` | X | `all` (전체 기간) 또는 `last` (최근만, 기본값) |
| `--clear` | X | 전체 데이터 삭제 |
| `--log-level` | X | 로그 레벨 (debug/info/warning/error, 기본: info) |

## 데이터 소스

- API: 네이버 금융 (`https://api.finance.naver.com/siseJson.naver`)
- 토큰 불필요

## 수집 데이터

| 항목 | 필드명 | 설명 |
|------|--------|------|
| 시가 | opening_price | 시가 |
| 고가 | high_price | 고가 |
| 저가 | low_price | 저가 |
| 종가 | closing_price | 종가 |
| 거래량 | trading_volume | 거래량 |

## 수집 범위

| 타임프레임 | all 모드 | last 모드 |
|------------|----------|-----------|
| 일봉 | 2년 (730일) | 30일 |
| 주봉 | 4년 (1460일) | 12주 |
| 월봉 | 6년 (2190일) | 12개월 |

## 저장 방식

- 기존 데이터가 있으면 UPDATE (덮어쓰기)
- 없으면 INSERT
- `DailyChartETF`, `WeeklyChartETF`, `MonthlyChartETF` 모델에 저장

## 자동 저장

ETF 관심종목 저장 시 (`/etf/` 페이지에서 "관심종목 저장" 클릭) 차트 데이터도 자동으로 저장됩니다 (mode=all).

따라서 `save_etf_chart` 명령어는 주로 정기 업데이트용으로 사용합니다.

## 출력 예시

```
# 단일 ETF
ETF: KODEX 2차전지산업(305720) | 모드: all
────────────────────────────────────────
결과: 일봉 +480/=0, 주봉 +208/=0, 월봉 +72/=0

# 전체 ETF
ETF 차트 저장 시작 (모드: last, 대상: 10개)
[1/10] 305720 KODEX 2차전지산업: 일봉 +1/=0, 주봉 +1/=0, 월봉 +0/=1
[2/10] 069500 KODEX 200: 일봉 +1/=0, 주봉 +1/=0, 월봉 +0/=1
...
────────────────────────────────────────
완료 | 성공: 10개
```

## 권장 사용법

1. **최초 실행**: ETF 관심종목 저장 시 자동으로 mode=all 실행됨
2. **정기 업데이트**: `--mode last`로 최근 데이터만 업데이트

```bash
# 일일 정기 업데이트
python manage.py save_etf_chart --mode last --log-level info
```

## 주의사항

- `InfoETF` 모델에 ETF가 등록되어 있어야 함 (is_active=True)
- 네이버 API 요청 간격: 0.5초
- 토큰 불필요 (네이버 금융 API 사용)
