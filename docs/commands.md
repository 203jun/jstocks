# 데이터 수집 명령어 총괄

주식 데이터 수집 및 저장을 위한 Django 관리 명령어 목록입니다.

## 명령어 목록 (21개)

| 분류 | 명령어 | 저장 모델 | 데이터 소스 | 실행 주기 |
|------|--------|-----------|-------------|-----------|
| 유틸 | `get_token` | token.json | 키움 API | 일 1회 |
| 유틸 | `check_market_open` | - | 키움 API | 일 1회 |
| 유틸 | `check_freshness` | - | DB | 일 1회 |
| 시황 | `save_index_chart` | IndexChart | 네이버 금융 | 일 1회 |
| 시황 | `save_market_trend` | MarketTrend | 네이버 (m.stock) | 일 1회 |
| AI | `run_ai_note` | AiNote | Claude Code (claude -p) | 수동 |
| 업종 | `save_sector` | Sector | 키움 API | 일 1회 |
| 종목 | `save_stock_list` | Info | 키움 API | 수동 |
| 종목 | `save_stock_info` | Info | 키움 API | 일 1회 |
| 종목 | `save_stock_sector` | Info.industry | 키움 API | 수동 |
| 종목 | `save_daily_chart` | DailyChart | 키움 API | 일 1회 |
| 종목 | `save_weekly_chart` | WeeklyChart | 키움 API | 일 1회 |
| 종목 | `save_monthly_chart` | MonthlyChart | 키움 API | 일 1회 |
| 종목 | `save_investor_trend` | InvestorTrend | 키움 API | 일 1회 |
| 종목 | `save_investor_daum` | InvestorTrend | 다음 금융 | 일 1회 |
| 종목 | `save_short_selling` | ShortSelling | 키움 API | 일 1회 |
| 종목 | `save_gongsi_stock` | Gongsi | DART | 일 1회 |
| 종목 | `save_fnguide_report` | Report | FnGuide | 일 1회 |
| 종목 | `save_nodaji_stock` | Nodaji | 네이버 프리미엄 | 일 1회 |
| ETF | `save_etf_chart` | *ChartETF | 네이버 금융 | 일 1회 |
| ETF | `save_etf_info` | InfoETF | 네이버 금융 | 일 1회 |
| 재무 | `save_financial_naver` | Financial | 네이버 금융 | 주 1회 |
| 재무 | `save_init_financial` | Financial | jemu 폴더 | 최초 1회 |

---

## 정기 업데이트

### 일일 (daily_update.sh)

```bash
python manage.py get_token
python manage.py check_market_open || exit 0

# 시황
python manage.py save_index_chart --mode last

# 종목
python manage.py save_stock_info --code all
python manage.py save_daily_chart --code all --mode last
python manage.py save_weekly_chart --code all --mode last
python manage.py save_monthly_chart --code all --mode last
python manage.py save_sector --mode last

# 관심 종목
python manage.py save_investor_trend --code fav --mode last
python manage.py save_short_selling --code fav --mode last
python manage.py save_gongsi_stock --code fav
python manage.py save_fnguide_report --code fav
python manage.py save_nodaji_stock --code fav

# ETF
python manage.py save_etf_chart --mode last
python manage.py save_etf_info
```

### 저녁 수급 (evening_update.sh)

수급은 장이 끝나고 한참 뒤에야 공개된다. 일일 배치(15:40)에서 받으면
전날 값이 오므로 수급만 따로 19:40 에 받는다.

```bash
python manage.py save_market_trend --mode last
python manage.py save_market_indicator --mode last
python manage.py save_investor_daum --code fav --mode last
```

### 주간 (weekly_update.sh)

```bash
python manage.py get_token
python manage.py save_financial_naver --code all
```

---

## 공통 옵션

| 옵션 | 설명 |
|------|------|
| `--code` | 종목코드 / "all" / "fav" |
| `--mode` | `all` (전체) / `last` (최근) |
| `--clear` | 데이터 삭제 |
| `--log-level` | debug / info / warning / error (기본: info) |

### 옵션 필수 여부

| 표시 | 의미 |
|------|------|
| O | 항상 필수 |
| O* | --clear 사용 시 불필요 |
| X | 선택 (기본값 있음) |

---

## 토큰 필요 명령어

**필요:**
- `get_token`, `check_market_open`
- `save_daily_chart`, `save_weekly_chart`, `save_monthly_chart`
- `save_investor_trend`, `save_short_selling`
- `save_sector`, `save_stock_sector`
- `save_stock_info`, `save_stock_list`

**불필요:**
- `save_etf_chart`, `save_etf_info`
- `save_index_chart`, `save_market_trend`
- `save_financial_naver`, `save_investor_daum`
- `save_fnguide_report`, `save_gongsi_stock`, `save_nodaji_stock`

---

## 실패를 알리는 방식

배치가 ✅ 로 끝났는데 실제로는 몇 달째 아무것도 안 들어오고 있던 일이
여러 번 있었다. 공시(크롬 바이너리), 시장 수급(주소가 410), ETF 정보
(네이버 화면 개편) 셋 다 조용히 멈췄다.

그래서 명령은 두 가지로 실패를 알린다. `batch_lib.sh` 가 둘 다 읽는다.

**1. 출력에 `오류: N개`** — 일부만 실패했을 때.

```
완료 | 신규: 12개, 업데이트: 3개, 오류: 2개

[오류 목록]
  005930 삼성전자: 조회 실패 - timeout
```

N 이 0 이 아니면 배치가 ⚠️ 를 보내고 단계 이름을 적는다.

**2. 종료코드 1 (`CommandError`)** — 한 건도 못 했을 때.

전부 실패는 대개 바깥이 바뀐 것이다(주소가 사라졌거나 응답 모양이
달라졌거나). 로그만 찍고 0 으로 끝나면 배치가 '완료' 를 보낸다.

새 수집 명령을 만들 때는 이 둘을 같이 넣는다.

**명령이 직접 텔레그램을 보내지 않는다.** 보내고 0 으로 끝나면 배치가 같은
자리에서 ✅ 를 함께 보내 알림 두 개가 서로 반대 말을 한다. 보내는 일은
`batch_lib.sh` 한 곳에서 하고, 거기에는 걸린 단계 이름과 마지막 출력이
같이 실린다.

### 이것으로도 안 잡히는 것

명령이 **성공했는데 입력이 썩은** 경우다. 시장 수급이 석 달 끊긴 동안
`save_market_indicator` 는 외인 20일 누적을 엉터리로 계산하면서 날마다
'완료' 를 찍었다. 자기 할 일은 다 했기 때문이다.

이것을 잡으려면 "어제까지 있던 데이터가 오늘 안 늘었다" 를 보는 쪽이
필요하다. 아직 없다.
