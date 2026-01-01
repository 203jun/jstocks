# save_stock_sector

키움 API에서 종목-업종 매핑 데이터를 저장합니다.

## 사용법

```bash
# 매핑 데이터 저장
python manage.py save_stock_sector

# 전체 매핑 삭제
python manage.py save_stock_sector --clear
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--clear` | X | 전체 매핑 삭제 |
| `--log-level` | X | debug / info / warning / error (기본: info) |

## 저장 모델

`Info.industry` (외래키)

## 데이터 소스

- API: 키움 Open API (`ka20002`)
- 토큰 필요

## 선행 조건

- `save_stock_list` 실행 완료
- `save_sector` 실행 완료

## 실행 주기

필요 시 수동 실행
