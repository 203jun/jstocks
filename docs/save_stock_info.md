# save_stock_info

종목 상세정보를 조회하고 저장하는 Django 관리 명령어입니다.

## 사용법

```bash
# 전체 종목 (기본 1000억 기준)
python manage.py save_stock_info --code all

# 시가총액 기준 변경
python manage.py save_stock_info --code all --min-cap 500

# 단일 종목
python manage.py save_stock_info --code 005930

# 로그 레벨 조정
python manage.py save_stock_info --code all --log-level info
```

## 옵션

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--code` | 종목코드 또는 `all` (전체 종목, ETF 제외) | (필수) |
| `--min-cap` | 최소 시가총액 (억 단위) | 1000 |
| `--log-level` | 로그 레벨 (debug/info/error) | debug |

## 동작 방식

1. Info 테이블에서 **ETF 제외** 전체 종목 대상
2. 각 종목마다 ka10001 API 호출 → **상세정보 저장**
3. 시가총액 기준으로 `is_active` 설정:
   - **1000억 이상** → `is_active=True`
   - **1000억 미만** → `is_active=False`

## 저장되는 정보

| 필드 | API 필드 | 설명 |
|------|----------|------|
| market_cap | mac | 시가총액 (억 단위) |
| listed_shares | flo_stk | 상장주식수 |
| per | per | PER |
| eps | eps | EPS |
| roe | roe | ROE |
| pbr | pbr | PBR |
| bps | bps | BPS |
| current_price | cur_prc | 현재가 |
| change_rate | flu_rt | 등락율 |
| volume | trde_qty | 거래량 |
| 등 | | |

## 출력 결과 해석

```
종목 상세정보 조회 시작 (2772개 종목, ETF 제외, 시가총액 1000억 기준 활성화/비활성화)
[1/2772] 000020 동화약품: 1715억
[2/2772] 000040 KR모터스: 430억 (비활성화됨)
[3/2772] 000050 경방: 1957억
[4/2772] 000100 유한양행: 95962억 (활성화됨)
...
종목 상세정보 조회 완료: 업데이트 1500개, 활성화 50개, 비활성화 900개, 오류 0개
```

| 로그 | 의미 |
|------|------|
| `1715억` | 시가총액, `is_active` 변경 없음 |
| `430억 (비활성화됨)` | 시가총액 1000억 미만으로 `is_active=False`로 변경됨 |
| `95962억 (활성화됨)` | 시가총액 1000억 이상으로 `is_active=True`로 변경됨 |

### 최종 요약

| 항목 | 의미 |
|------|------|
| **업데이트** | `is_active` 변경 없이 정보만 업데이트된 종목 수 |
| **활성화** | `is_active=False` → `True`로 변경된 종목 수 |
| **비활성화** | `is_active=True` → `False`로 변경된 종목 수 |
| **오류** | API 호출 실패한 종목 수 |

## 관련 API

- 키움 API: `ka10001` (주식기본정보요청)
- Endpoint: `/api/dostk/stkinfo`

## 주의사항

- ETF는 처리 대상에서 **제외**됩니다 (시가총액 개념이 다름)
- API 호출 간격: 0.1초 (전체 종목 약 4~5분 소요)
- `mac` 필드는 **억 단위**입니다

## 실행 순서 (권장)

```bash
# 1. 종목 목록 동기화
python manage.py save_stock_list

# 2. 종목 상세정보 저장 + 시가총액 필터링
python manage.py save_stock_info --code all
```
