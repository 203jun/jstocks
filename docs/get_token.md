# get_token

키움 API 토큰 발급 및 저장

## 사용법

```bash
python manage.py get_token
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--log-level` | X | 로그 레벨 (debug/info/warning/error, 기본: info) |

## 데이터 소스

- API: 키움 Open API (`https://api.kiwoom.com`)
- 토큰 저장 위치: `token.json`

## 실행 주기

일 1회 (daily_update.sh 첫 단계)

## 주의사항

- 키움 API 사용 전 반드시 실행 필요
- `.env` 파일에 `KIWOOM_APP_KEY`, `KIWOOM_SECRET_KEY` 설정 필요
