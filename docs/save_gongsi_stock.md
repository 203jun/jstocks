# save_gongsi_stock

DART 공시 조회 및 저장

## 저장 모델

`Gongsi`

## 사용법

```bash
# 특정 종목
python manage.py save_gongsi_stock --code 005930

# 전체 종목
python manage.py save_gongsi_stock --code all

# 관심 종목만 (interest_level 설정된 종목)
python manage.py save_gongsi_stock --code fav
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--code` | O | 종목코드 또는 `all` / `fav` |
| `--log-level` | X | 로그 레벨 (debug/info/warning/error, 기본: info) |
| `--clear` | X | 전체 데이터 삭제 |

### --code 옵션 값

| 값 | 설명 |
|----|------|
| `종목코드` | 특정 종목만 처리 (예: 005930) |
| `all` | 전체 종목 처리 (is_active=True) |
| `fav` | 관심 종목만 처리 (interest_level이 설정된 종목: 초관심/관심/인큐베이터) |

## 데이터 소스

DART 전자공시시스템

## 실행 주기

일 1회 (장 마감 후)
