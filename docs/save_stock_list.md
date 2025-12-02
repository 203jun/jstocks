# save_stock_list

상장 종목 목록을 동기화하는 Django 관리 명령어입니다.

## 사용법

```bash
# 전체 종목 동기화 (ETF → KOSPI → KOSDAQ 순서)
python manage.py save_stock_list

# 간단한 로그만 출력
python manage.py save_stock_list --log-level info

# Info 테이블 전체 삭제 (연결된 모든 데이터 함께 삭제)
python manage.py save_stock_list --clear
```

## 옵션

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--clear` | Info 테이블 전체 삭제 (Financial, Chart 등 연결 데이터 모두 삭제) | - |
| `--log-level` | 로그 레벨 (debug/info/error) | debug |

## 처리 순서

1. **ETF** (시장코드: 8)
2. **KOSPI** (시장코드: 0) - ETN/ETF 제외
3. **KOSDAQ** (시장코드: 10)

ETF를 먼저 처리하는 이유: KOSPI API 응답에 ETF 종목이 포함되어 있어서 중복 방지를 위해 ETF 코드를 먼저 수집 후 KOSPI에서 제외합니다.

## 필터링 규칙

### KOSPI/KOSDAQ
- `kind='A'` (일반주식)만 저장
- ETN (`kind='Q'`) 제외
- ETF 코드 제외
- 스팩(SPAC) 제외 (종목명이 '스팩'으로 끝나는 종목)

### ETF
- 필터링 없이 전체 저장

## 출력 결과 해석

```
ETF 종목 목록 조회 시작...
응답 코드: 200
ETF 동기화 완료: API 1049개, 신규 1049개, 업데이트 0개, 상폐 0개
```

| 항목 | 의미 |
|------|------|
| **API** | API 응답에서 받은 종목 수 (필터링 후) |
| **신규** | DB에 없어서 새로 INSERT한 종목 수 |
| **업데이트** | 이미 존재하지만 시장 변경 또는 재활성화된 종목 수 |
| **상폐** | DB에는 있지만 API에 없어서 `is_active=False` 처리된 종목 수 |

### 신규 (INSERT)
- API에는 있고 DB에는 없는 종목
- 새로 상장된 종목

### 업데이트 (UPDATE)
- 코드가 DB에 존재하지만:
  - 다른 시장으로 등록되어 있는 경우 (시장 변경)
  - `is_active=False`인 경우 (재상장/재활성화)

### 상폐 (DELISTED)
- DB에는 `is_active=True`로 있지만 API 응답에 없는 종목
- `is_active=False`로 변경됨
- 로그에 강한 경고(ERROR)로 표시됨 (추후 텔레그램 알림 연동 예정)

## 두 번째 실행 시 모두 0인 경우

```
ETF 동기화 완료: API 1049개, 신규 0개, 업데이트 0개, 상폐 0개
KOSPI 동기화 완료: API 960개, 신규 0개, 업데이트 0개, 상폐 0개
KOSDAQ 동기화 완료: API 1812개, 신규 0개, 업데이트 0개, 상폐 0개
```

정상입니다. 이미 모든 종목이 올바른 시장으로 `is_active=True` 상태로 저장되어 있어서 변경할 내용이 없습니다.

## 관련 API

- 키움 API: `ka10099` (종목정보 리스트)
- Endpoint: `/api/dostk/stkinfo`

## 시장 구분 코드

| 코드 | 시장 | 비고 |
|------|------|------|
| 0 | KOSPI | ETN 포함 (kind='Q'로 필터링) |
| 10 | KOSDAQ | |
| 8 | ETF | |
| 3 | ELW | 미사용 |
| 30 | K-OTC | 미사용 |
| 50 | 코넥스 | 미사용 |

## --clear 시 삭제되는 테이블

Info 삭제 시 `on_delete=CASCADE`로 연결된 모든 데이터가 함께 삭제됩니다:

- `info` (종목정보)
- `financial` (재무제표)
- `daily_chart` (일봉)
- `weekly_chart` (주봉)
- `monthly_chart` (월봉)
- `investor_trend` (투자자동향)
- `short_selling` (공매도)
- `info_themes` (종목-테마 관계)
- `info_sectors` (종목-업종 관계)
