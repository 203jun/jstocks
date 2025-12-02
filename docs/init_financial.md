# init_financial

재무제표 초기 데이터를 로드하는 Django 관리 명령어입니다. (jemu 폴더의 txt 파일 사용)

## 사용법

```bash
# 단일 종목 - 연간+분기 둘 다
python manage.py init_financial --code 005930

# 단일 종목 - 연간만
python manage.py init_financial --code 005930 --mode annual

# 단일 종목 - 분기만
python manage.py init_financial --code 005930 --mode quarterly

# 전체 종목 - 연간+분기 둘 다
python manage.py init_financial --code all

# 전체 종목 - 연간만
python manage.py init_financial --code all --mode annual

# 로그 레벨 조정
python manage.py init_financial --code all --log-level info
```

## 옵션

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--code` | 종목코드 또는 `all` (전체 종목, ETF 제외) | (필수) |
| `--mode` | 데이터 유형 (annual/quarterly/all) | all |
| `--log-level` | 로그 레벨 (debug/info/error) | debug |

## 동작 방식

1. `jemu` 폴더에서 포괄손익계산서 txt 파일 로드
2. 각 종목의 매출액, 영업이익, 순이익 추출
3. Financial 테이블에 저장
4. 전년 대비 증가율 계산

## 데이터 유형

### 연간 (annual)
- 4Q(사업보고서) 데이터 = 연간 누적 값
- `quarter = NULL`로 저장

### 분기 (quarterly)
- 1Q, 2Q, 3Q: 각 분기 3개월 실적
- 4Q: 연간 누적 - (1Q + 2Q + 3Q) 보정 적용
- `quarter = '1Q'/'2Q'/'3Q'/'4Q'`로 저장

## 저장되는 정보

| 필드 | 설명 |
|------|------|
| revenue | 매출액 (원) |
| operating_profit | 영업이익 (원) |
| net_income | 순이익 (원) |
| revenue_growth | 매출액 증가율 (%) |
| operating_profit_growth | 영업이익 증가율 (%) |
| net_income_growth | 순이익 증가율 (%) |

## 출력 결과 해석

```
재무제표 초기 데이터 로드 시작 (연간, 1467개 종목, ETF 제외)
[1/1467] 000020 동화약품: 연간 5건
[2/1467] 000050 경방: 연간 5건
[3/1467] 000070 삼양홀딩스: 데이터 없음
[4/1467] 000080 하이트진로: 연간 3건
...
재무제표 초기 데이터 로드 완료: 성공 1200개, 데이터없음 267개, 오류 0개
```

| 로그 | 의미 |
|------|------|
| `연간 5건` | 5개 연도 데이터 저장됨 (2020~2024) |
| `연간 3건` | 3개 연도 데이터만 존재 (일부 연도 누락) |
| `데이터 없음` | 해당 종목의 재무 데이터가 전혀 없음 |

### 최종 요약

| 항목 | 의미 |
|------|------|
| **성공** | 1건 이상 재무 데이터가 저장된 종목 수 |
| **데이터없음** | jemu 폴더에 해당 종목 데이터가 전혀 없는 경우 |
| **오류** | 처리 중 에러 발생한 종목 수 |

### 일부 연도만 있는 경우

- 있는 데이터만 저장됩니다 (누락된 연도는 무시)
- 예: 2020, 2021, 2022년만 있으면 → "연간 3건"
- 모든 연도에 데이터가 없을 때만 → "데이터 없음"

## 데이터 소스

- OpenDART에서 다운로드한 재무제표 txt 파일
- 파일 위치: `jemu/` 폴더
- 파일 형식: `2024_1분기보고서_03_포괄손익계산서_20250221.txt`

## 주의사항

- ETF는 처리 대상에서 **제외**됩니다
- `is_active=True`인 종목만 처리됩니다
- 최초 1회 실행용 (이후 업데이트는 별도 명령어 사용)

## 실행 순서 (권장)

```bash
# 1. 종목 목록 동기화
python manage.py save_stock_list

# 2. 종목 상세정보 저장 + 시가총액 필터링
python manage.py save_stock_info --code all

# 3. 재무제표 초기 데이터 로드
python manage.py init_financial --code all
```
