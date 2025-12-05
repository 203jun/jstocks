# save_stock_sector

종목-업종 매핑 데이터 저장 (키움 API ka20002)

## 저장 모델

`Info.sectors` (ManyToMany 관계)

## 사용법

```bash
# 전체 업종에 대해 종목 매핑
python manage.py save_stock_sector

# 디버그 모드
python manage.py save_stock_sector --log-level debug
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--log-level` | X | 로그 레벨 (debug/info/warning/error, 기본: info) |

## 데이터 소스

- API: 키움 Open API (ka20002 - 업종별주가요청)
- 토큰 필요: `python manage.py get_token` 먼저 실행

## 동작 방식

1. Sector 테이블에서 모든 고유한 (업종코드, 시장) 조합 가져오기
2. 각 업종별로 ka20002 API 호출
3. Info.sectors에 매핑 (ManyToMany 관계 연결)

## 선행 조건

```bash
# 먼저 실행 필요
python manage.py save_sector --mode all
```

## 주의사항

- Sector 테이블이 비어있으면 실행 불가
- 종목당 0.5초 대기 (API 호출 제한 방지)

## 실행 주기

주 1회 (업종 구성 변경 시)
