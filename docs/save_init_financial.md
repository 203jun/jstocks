# save_init_financial

재무제표 초기 데이터를 로드합니다. (jemu 폴더의 txt 파일 사용)

## 사용법

```bash
# 전체 종목
python manage.py save_init_financial --code all

# 단일 종목
python manage.py save_init_financial --code 005930

# 연간 데이터만
python manage.py save_init_financial --code all --type annual

# 분기 데이터만
python manage.py save_init_financial --code all --type quarterly

# 데이터 삭제
python manage.py save_init_financial --clear
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--code` | O* | 종목코드 또는 "all" |
| `--type` | X | `annual` / `quarterly` / `all` (기본: all) |
| `--clear` | X | 전체 데이터 삭제 |
| `--log-level` | X | debug / info / warning / error (기본: info) |

\* --clear 사용 시 불필요

## 저장 모델

`Financial`

## 데이터 소스

- 파일: `jemu/` 폴더의 포괄손익계산서 txt 파일
- DART 재무제표 다운로드 후 사용

## 수집 데이터

| 항목 | 필드명 |
|------|--------|
| 매출액 | revenue |
| 영업이익 | operating_profit |
| 순이익 | net_income |

## 실행 주기

최초 1회 (수동)
