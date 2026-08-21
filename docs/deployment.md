# 서버 배포 가이드

jstocks 프로젝트를 서버에 배포하기 위한 가이드입니다.

---

## 서버 요구사항

- Python 3.10 이상
- pip
- Git
- SQLite3 (기본) 또는 PostgreSQL/MySQL

---

## 1. 프로젝트 클론

```bash
git clone <repository-url> jstocks
cd jstocks
```

---

## 2. 가상환경 설정

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 또는
venv\Scripts\activate     # Windows
```

---

## 3. 패키지 설치

```bash
pip install -r requirements.txt
```

---

## 4. Playwright 브라우저 설치

노다지(네이버 프리미엄 콘텐츠) 검색 기능을 위해 Playwright 브라우저를 설치해야 합니다.

```bash
# Chromium 브라우저 설치
playwright install chromium
```

**Linux 서버인 경우** 시스템 의존성도 설치합니다:

```bash
playwright install-deps chromium
playwright install chromium
```

**주의:** requirements.txt로는 브라우저 바이너리가 설치되지 않습니다. 반드시 위 명령어를 실행해야 합니다.

---

## 5. 환경 변수 설정

`.env` 파일을 프로젝트 루트에 생성합니다:

```bash
# Django 설정
SECRET_KEY=your-secret-key-here
DEBUG=False
ALLOWED_HOSTS=your-domain.com,your-ip

# 키움 API (선택)
KIWOOM_APP_KEY=your-app-key
KIWOOM_APP_SECRET=your-app-secret
KIWOOM_ACCOUNT=your-account

# Telegram API (선택)
TELEGRAM_API_ID=your-api-id
TELEGRAM_API_HASH=your-api-hash

# DART API (선택)
DART_API_KEY=your-dart-api-key
```

---

## 6. 데이터베이스 마이그레이션

```bash
python manage.py migrate
```

---

## 7. 정적 파일 수집

```bash
python manage.py collectstatic --noinput
```

---

## 8. 서버 실행

### 개발 서버

```bash
python manage.py runserver 0.0.0.0:8000
```

### 프로덕션 서버 (Gunicorn)

```bash
gunicorn jstocks.wsgi:application --bind 0.0.0.0:8000
```

백그라운드 실행:

```bash
nohup gunicorn jstocks.wsgi:application --bind 0.0.0.0:8000 > gunicorn.log 2>&1 &
```

---

## 9. 초기 데이터 수집

배포 후 초기 데이터를 수집합니다. 자세한 내용은 [commands.md](./commands.md)를 참조하세요.

```bash
# 토큰 발급 (키움 API 사용 시)
python manage.py get_token

# 종목 목록 수집
python manage.py save_stock_list --log-level info

# 종목 기본 정보
python manage.py save_stock_info --code all --log-level info
```

---

## 업데이트 배포

```bash
# 코드 업데이트
git pull origin main

# 패키지 업데이트
pip install -r requirements.txt

# Playwright 업데이트 (버전 변경 시)
playwright install chromium

# 마이그레이션
python manage.py migrate

# 정적 파일 수집
python manage.py collectstatic --noinput

# 서버 재시작
pkill gunicorn
nohup gunicorn jstocks.wsgi:application --bind 0.0.0.0:8000 > gunicorn.log 2>&1 &
```

---

## 문제 해결

### Playwright 관련 오류

**"No module named 'playwright'"**
```bash
pip install playwright
```

**"Executable doesn't exist at ..."**
```bash
playwright install chromium
```

**Linux에서 브라우저 실행 오류**
```bash
playwright install-deps chromium
```

### 권한 오류

```bash
chmod +x manage.py
```

### 포트 사용 중 오류

```bash
# 사용 중인 프로세스 확인
lsof -i :8000

# 프로세스 종료
kill -9 <PID>
```
