# save_nodaji_stock

노다지 IR노트 기사 조회 및 저장 (네이버 프리미엄 콘텐츠)

## 저장 모델

`Nodaji`

## 사용법

```bash
# 특정 종목
python manage.py save_nodaji_stock --code 005930

# 전체 종목 (ETF 제외)
python manage.py save_nodaji_stock --code all

# 디버그 모드
python manage.py save_nodaji_stock --code 005930 --log-level debug
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--code` | O | 종목코드 또는 `all` (전체 종목, ETF 제외) |
| `--log-level` | X | 로그 레벨 (debug/info/warning/error, 기본: info) |

## 데이터 소스

- 네이버 프리미엄 콘텐츠 (노다지 IR노트)
- URL: `https://contents.premium.naver.com/ystreet/irnote/search`
- Playwright 사용 (헤드리스 브라우저)

## 수집 데이터

| 항목 | 필드명 | 설명 |
|------|--------|------|
| 제목 | title | 기사 제목 |
| 날짜 | date | 기사 작성일 |
| 링크 | link | 기사 URL |
| 요약 | summary | 기사 요약 (추후 추가) |

## 동작 방식

1. 종목명으로 노다지 IR노트 검색
2. 검색 결과에서 최대 20개 기사 추출
3. 링크로 중복 체크 후 신규 기사만 저장

## 주의사항

- Playwright 설치 필요: `pip install playwright && playwright install chromium`
- 전체 종목 처리 시 종목당 1초 대기 (API 제한 방지)
- ETF는 처리 대상에서 제외

## 실행 주기

일 1회 (장 마감 후)
