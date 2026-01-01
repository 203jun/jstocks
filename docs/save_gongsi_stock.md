# save_gongsi_stock

DART에서 공시 데이터를 조회하여 저장합니다.

## 사용법

```bash
# 관심 종목 (정기 업데이트용)
python manage.py save_gongsi_stock --code fav

# 전체 종목
python manage.py save_gongsi_stock --code all

# 단일 종목
python manage.py save_gongsi_stock --code 005930

# 데이터 삭제
python manage.py save_gongsi_stock --clear
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--code` | O* | 종목코드 / "all" / "fav" |
| `--clear` | X | 데이터 삭제 |
| `--log-level` | X | debug / info / warning / error (기본: info) |

\* --clear 사용 시 불필요

## 저장 모델

`Gongsi`

## 데이터 소스

- API: DART Open API
- 토큰 필요 (DART API KEY)

## 수집 데이터

| 항목 | 필드명 |
|------|--------|
| 공시일자 | date |
| 제목 | title |
| 보고서 링크 | report_link |
| 공시 유형 | report_type |

## 실행 주기

일 1회 (daily_update.sh)
