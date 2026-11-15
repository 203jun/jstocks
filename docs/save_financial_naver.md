# save_financial_naver

네이버에서 재무제표를 받아 저장합니다. 연간 4기, 분기 6기.

## 사용법

```bash
# 전체 종목
python manage.py save_financial_naver --code all

# 단일 종목
python manage.py save_financial_naver --code 005930

# 데이터 삭제
python manage.py save_financial_naver --clear
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--code` | O* | 종목코드 또는 "all" |
| `--clear` | X | 전체 데이터 삭제 |
| `--log-level` | X | debug / info / warning / error (기본: info) |

\* --clear 사용 시 불필요

## 저장 모델

`Financial`

## 데이터 소스

```
GET https://m.stock.naver.com/api/stock/{code}/finance/annual
GET https://m.stock.naver.com/api/stock/{code}/finance/quarter
```

토큰 불필요. 금액은 억원으로 와서 원 단위로 바꿔 저장한다.

마지막 기간은 대개 컨센서스(추정치)다. 응답의 `trTitleList[].isConsensus`
가 `'Y'` 면 `is_estimated=True` 로 넣는다 — 예전에는 머리글의 `(E)` 를
정규식으로 찾아냈다.

예전에는 `finance.naver.com/item/main.naver` 의 재무 테이블을 CSS 셀렉터로
긁었다. 네이버가 그 화면을 Next.js 앱으로 다시 만들면서 구조가 통째로
사라졌다 — 주소는 그대로 200 을 주고 셀렉터만 안 맞는다. 지금은 필드가
없으면 예외가 나고, 한 종목도 못 받으면 종료코드 1 로 끝난다.

1,576종목에 약 11분 걸린다 (종목당 요청 2회, 0.3초 간격).

## 수집 데이터

| 항목 | 필드명 |
|------|--------|
| 매출액 | revenue |
| 영업이익 | operating_profit |
| 당기순이익 | net_income |
| 영업이익률 | operating_margin |
| 순이익률 | net_margin |
| ROE | roe |

응답에는 이 여섯 말고도 열 가지가 더 온다 — 지배주주순이익, 비지배주주순이익,
부채비율, 당좌비율, 유보율, EPS, PER, BPS, PBR, 주당배당금. `Financial` 에
칸이 없어 버린다. 쓸 일이 생기면 `FIELD_MAP` 에 더하면 된다.

`ROE` 는 예전 화면에 `ROE(지배주주)` 로 적혀 있던 것이다. 상용에 쌓인
2023·2024·2025 값과 대조해 같은 값임을 확인했다 (4.15 / 9.03 / 10.85).

## 실행 주기

주 1회 (weekly_update.sh)
