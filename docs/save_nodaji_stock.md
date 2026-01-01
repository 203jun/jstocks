# save_nodaji_stock

노다지 IR노트 기사를 조회하여 저장합니다. (네이버 프리미엄 콘텐츠)

## 사용법

```bash
# 관심 종목 (정기 업데이트용)
python manage.py save_nodaji_stock --code fav

# 전체 종목
python manage.py save_nodaji_stock --code all

# 단일 종목
python manage.py save_nodaji_stock --code 005930

# 데이터 삭제
python manage.py save_nodaji_stock --clear
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--code` | O* | 종목코드 / "all" / "fav" |
| `--clear` | X | 데이터 삭제 |
| `--log-level` | X | debug / info / warning / error (기본: info) |

\* --clear 사용 시 불필요

## 저장 모델

`Nodaji`

## 데이터 소스

- URL: 네이버 프리미엄 콘텐츠 (`contents.premium.naver.com`)
- Playwright 필요

## 수집 데이터

| 항목 | 필드명 |
|------|--------|
| 날짜 | date |
| 제목 | title |
| 링크 | link |

## 실행 주기

일 1회 (daily_update.sh)
