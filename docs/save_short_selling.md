# save_short_selling

공매도 추이 저장 (키움 API ka10014)

## 저장 모델

`ShortSelling`

## 사용법

```bash
# 특정 종목, 최근 1일
python manage.py save_short_selling --code 005930 --mode last

# 특정 종목, 60일
python manage.py save_short_selling --code 005930 --mode all

# 전체 종목, 최근 1일
python manage.py save_short_selling --code all --mode last

# 전체 종목, 60일
python manage.py save_short_selling --code all --mode all

# 디버그 모드
python manage.py save_short_selling --code 005930 --mode last --log-level debug
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--code` | O | 종목코드 (예: 005930) 또는 `all` (전체 종목) |
| `--mode` | O | `all` (60일) 또는 `last` (최근 1일) |
| `--log-level` | X | 로그 레벨 (debug/info/warning/error, 기본: info) |

## 데이터 소스

- API: 키움 Open API (ka10014 - 공매도추이요청)
- 토큰 필요: `python manage.py get_token` 먼저 실행

## 수집 데이터

| 항목 | 필드명 | 설명 |
|------|--------|------|
| 거래량 | trading_volume | 일 거래량 |
| 공매도량 | short_volume | 공매도 거래량 |
| 누적공매도량 | cumulative_short_volume | 누적 공매도량 |
| 비중 | trading_weight | 공매도 비중 (%) |
| 공매도대금 | short_trading_value | 공매도 거래대금 |
| 공매도평균가 | short_average_price | 공매도 평균가 |

## 실행 주기

일 1회 (장 마감 후)
