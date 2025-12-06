# save_weekly_chart

키움 API에서 주봉 차트 데이터를 조회하여 저장합니다.

## 사용법

```bash
# 단일 종목, 4년치 데이터 (최초 1회)
python manage.py save_weekly_chart --code 005930 --mode all

# 단일 종목, 최근 1주만
python manage.py save_weekly_chart --code 005930 --mode last

# 전체 종목, 4년치 (최초 1회)
python manage.py save_weekly_chart --code all --mode all

# 전체 종목, 최근 1주만 (정기 업데이트용)
python manage.py save_weekly_chart --code all --mode last

# 디버그 모드
python manage.py save_weekly_chart --code 005930 --mode all --log-level debug
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--code` | O | 종목코드 또는 "all" (전체 종목) |
| `--mode` | O | `all` (4년 데이터) 또는 `last` (최근 1주만) |
| `--log-level` | X | 로그 레벨 (debug/info/warning/error, 기본: info) |

## 데이터 소스

- API: 키움 Open API (ka10082 - 주식주봉차트조회요청)
- 토큰 필요: `python manage.py get_token` 먼저 실행

## 수집 데이터

| 항목 | 필드명 | 설명 |
|------|--------|------|
| 시가 | opening_price | 주 시가 |
| 고가 | high_price | 주 고가 |
| 저가 | low_price | 주 저가 |
| 종가 | closing_price | 주 종가 |
| 전주대비 | price_change | 전주 대비 가격 변동 |
| 거래량 | trading_volume | 주 거래량 |
| 거래대금 | trading_value | 주 거래대금 |

## 수집 범위

- `--mode all`: 최근 4년치 (연속조회로 전체 수집)
- `--mode last`: 최근 1주만

## 저장 방식

- 기존 데이터가 있으면 UPDATE (덮어쓰기)
- 없으면 INSERT
- `WeeklyChart` 모델에 저장

## 전체 종목 처리 시

- `is_active=True`인 종목만 처리
- 요청 간격: 0.1초
- 처리 완료 후 최종 리포트 출력 (성공/데이터없음/오류)

## 출력 예시

```
# 단일 종목
종목코드: 005930 | 모드: all
4년 데이터 조회
저장 완료: 신규 208건, 업데이트 0건

# 전체 종목
주봉 차트 조회 시작 (최근 1주만, 2714개 종목)
[1/2714] 005930 삼성전자: 신규 0, 업데이트 1
[2/2714] 000660 SK하이닉스: 신규 1, 업데이트 0
[3/2714] 373220 LG에너지솔루션: 데이터 없음
...
======================================================================
주봉 차트 조회 완료: 성공 2700개, 데이터없음 10개, 오류 4개

[데이터 없음] 10개:
  - 000020 동화약품
  - 000040 KR모터스
  ... 외 8개

[오류 발생] 4개:
  - 123456 ABC기업: 토큰 만료
  - 234567 DEF주식: API 호출 실패
```

## 권장 사용법

1. 최초 실행: `--mode all`로 4년치 데이터 수집
2. 이후 정기 업데이트: `--mode last`로 최근 1주만 업데이트

## 주의사항

- `Info` 모델에 종목이 등록되어 있어야 함
- 토큰이 유효해야 함 (만료 시 `get_token` 재실행)
- 전체 종목 처리 시 약 5분 소요 (2700개 기준)
