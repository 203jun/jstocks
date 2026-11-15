# save_etf_info

네이버에서 ETF 정보를 받아 저장합니다.

## 사용법

```bash
# 전체 ETF (정기 업데이트용)
python manage.py save_etf_info

# 단일 ETF
python manage.py save_etf_info --etf-code 305720
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--etf-code` | X | ETF 코드 또는 "all" (기본: all) |
| `--log-level` | X | debug / info / warning / error (기본: info) |

## 저장 모델

`InfoETF`

## 데이터 소스

```
GET https://m.stock.naver.com/api/stock/{code}/basic         현재가·등락률
GET https://m.stock.naver.com/api/stock/{code}/etfAnalysis   NAV·시총·보수·구성종목
```

토큰 불필요.

예전에는 `finance.naver.com/item/main.naver` 화면을 CSS 셀렉터로 긁었다.
네이버가 그 화면을 Next.js 앱으로 다시 만들면서 예전 구조가 통째로 사라졌다.
주소는 그대로 200 을 주고 셀렉터만 안 맞아서, 값이 넉 달 가까이 멈춘 채
'성공' 으로 끝나고 있었다 — 대시보드가 차트보다 최대 163% 높은 값을
보여주고 있었다.

지금은 필드가 없으면 예외가 나고 `오류: N개` 로 올라간다. 전부 실패하면
종료코드 1 이라 배치가 텔레그램을 보낸다.

## 수집 데이터

| 항목 | 필드명 |
|------|--------|
| 현재가 | current_price |
| 등락률 | change_rate |
| NAV | nav |
| 시가총액 | market_cap |
| 총보수 | management_fee |
| 구성종목 | holdings |

구성종목은 상위 10개이며 `{name, ratio, code}` 로 담는다. 예전 HTML 에서는
이름과 비중만 긁었다 — `code` 가 생겨 보유 종목과 이어 볼 수 있다.

시가총액은 `marketValueRaw`(원 단위 정수)를 억원으로 나눈 값이다. 예전에는
`"21조 6,016억"` 문자열을 정규식으로 뜯었다.

현재가와 등락률은 없으면 그 ETF 를 실패로 처리한다. 화면이 보여주는 값이라
옛날 값이 남으면 사람이 틀린 숫자를 보고 판단한다. 비어 있는 편이 낫다.
NAV·시총·보수·구성종목은 없어도 넘어간다 — ETF 마다 안 주는 항목이 있다.

## 실행 주기

일 1회 (daily_update.sh)
