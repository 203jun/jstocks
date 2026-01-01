# save_stock_list

키움 API에서 상장 종목 목록을 동기화합니다.

## 사용법

```bash
# 종목 목록 동기화
python manage.py save_stock_list

# 전체 데이터 삭제 (주의: 연결된 모든 데이터 삭제됨)
python manage.py save_stock_list --clear
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--clear` | X | Info 테이블 전체 삭제 |
| `--log-level` | X | debug / info / warning / error (기본: info) |

## 저장 모델

`Info`

## 데이터 소스

- API: 키움 Open API (`ka10000`)
- 토큰 필요

## 필터링 규칙

제외 대상:
- 스팩 (SPAC)
- 리츠 (REIT)
- 우선주 (종목명 끝 숫자)
- ETF/ETN

## 실행 주기

필요 시 수동 실행
