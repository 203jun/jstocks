# save_sector

키움 API에서 업종별 투자자 순매수 데이터를 저장합니다.

## 사용법

```bash
# 최근 1일 (정기 업데이트용)
python manage.py save_sector

# 최근 60거래일
python manage.py save_sector --mode all

# 데이터 삭제
python manage.py save_sector --clear
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--mode` | X | `all` (60거래일) / `last` (1일, 기본) |
| `--clear` | X | 전체 데이터 삭제 |
| `--log-level` | X | debug / info / warning / error (기본: info) |

## 저장 모델

`Sector`

## 데이터 소스

- API: 키움 Open API (`ka10051`)
- 토큰 필요

## 수집 데이터

| 항목 | 필드명 |
|------|--------|
| 개인 순매수 | individual_net_buying |
| 외국인 순매수 | foreign_net_buying |
| 기관 순매수 | institution_net_buying |

## 실행 주기

일 1회 (daily_update.sh, 일봉 차트 이후)
