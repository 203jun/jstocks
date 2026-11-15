# save_market_trend

네이버에서 코스피·코스닥의 투자자별 매매동향(개인·외국인·기관)을 일별로 저장합니다.

## 사용법

```bash
# 전체 시장, 최근 1영업일 (정기 업데이트용)
python manage.py save_market_trend

# 전체 시장, 60영업일
python manage.py save_market_trend --mode all

# 특정 시장만
python manage.py save_market_trend --market KOSPI

# 과거 백필 (약 1년)
python manage.py save_market_trend --days 250

# 데이터 삭제
python manage.py save_market_trend --clear
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--market` | X | KOSPI / KOSDAQ / all (기본: all) |
| `--mode` | X | `all` (60영업일) / `last` (1영업일, 기본) |
| `--days` | X | 받아올 영업일 수. 지정하면 `--mode` 보다 우선 |
| `--clear` | X | 전체 데이터 삭제 |
| `--log-level` | X | debug / info / warning / error (기본: info) |

## 저장 모델

`MarketTrend`

## 데이터 소스

```
GET https://m.stock.naver.com/api/index/{KOSPI|KOSDAQ}/trend?bizdate=YYYYMMDD
```

```json
{"bizdate":"20261113","personalValue":"+145",
 "foreignValue":"-5,419","institutionalValue":"-59"}
```

- 토큰 불필요. 단위는 억원
- 날짜를 하루씩 거꾸로 훑으며 하나씩 받는다 (0.2초 간격)
- 휴장일·미래 날짜도 200 을 주면서 세 값만 `"0"` 으로 돌려준다 → 저장하지 않고 건너뛴다

예전에는 `finance.naver.com/sise/investorDealTrendDay.naver` 화면을 긁어
금융투자·투신·은행 등 11개 항목을 받았다. 네이버가 그 주소를 410 으로 내리면서
수급이 끊겼고, 대신 쓸 만한 곳으로 이 API 를 찾았다. 보는 화면이 개인·외국인·기관
셋만 쓰므로 나머지 항목과 선물(FUTURES)은 걷었다.

## 수집 데이터

| 항목 | 필드명 |
|------|--------|
| 개인 | individual |
| 외국인 | foreign |
| 기관 | institution |

## 실행 주기

일 1회 (evening_update.sh, 평일 19:40)
