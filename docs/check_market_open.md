# check_market_open

오늘이 장 운영일인지 확인 (휴장일이면 exit 1)

## 사용법

```bash
python manage.py check_market_open

# daily_update.sh에서 사용 예시
python manage.py check_market_open || exit 0
```

## 옵션

없음

## 동작 방식

1. 삼성전자(005930)의 오늘 일봉 데이터 조회
2. 데이터가 있으면 장 운영일 (exit 0)
3. 데이터가 없으면 휴장일 (exit 1)

## 데이터 소스

- API: 키움 Open API (`ka10081`)
- 토큰 필요

## 실행 주기

일 1회 (daily_update.sh에서 토큰 발급 후 실행)

## 반환값

| 상태 | exit code | 설명 |
|------|-----------|------|
| 장 운영일 | 0 | 스크립트 계속 실행 |
| 휴장일 | 1 | 스크립트 종료 |
