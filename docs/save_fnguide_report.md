# save_fnguide_report

FnGuide에서 애널리스트 리포트를 조회하여 저장합니다.

## 사용법

```bash
# 관심 종목 (정기 업데이트용)
python manage.py save_fnguide_report --code fav

# 전체 종목
python manage.py save_fnguide_report --code all

# 단일 종목
python manage.py save_fnguide_report --code 005930

# 데이터 삭제
python manage.py save_fnguide_report --clear
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--code` | O* | 종목코드 / "all" / "fav" |
| `--clear` | X | 데이터 삭제 |
| `--log-level` | X | debug / info / warning / error (기본: info) |

\* --clear 사용 시 불필요

## 저장 모델

`Report`

## 데이터 소스

- API: FnGuide (`comp.wisereport.co.kr`)
- 토큰 불필요

## 수집 데이터

| 항목 | 필드명 |
|------|--------|
| 날짜 | date |
| 제목 | title |
| 애널리스트 | author |
| 증권사 | provider |
| 목표가 | target_price |
| 투자의견 | recommendation |

## 실행 주기

일 1회 (daily_update.sh)
