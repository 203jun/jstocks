# save_gongsi_stock

DART 공시 조회 및 저장

## 저장 모델

`Gongsi`

## 사용법

```bash
python manage.py save_gongsi_stock --code 005930    # 특정 종목
python manage.py save_gongsi_stock --code all       # 전체 종목 (ETF 제외)
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--code` | O | 종목코드 또는 `all` (전체 종목) |

## 데이터 소스

DART 전자공시시스템

## 실행 주기

일 1회 (장 마감 후)
