# 서버 배포 가이드

지금 돌고 있는 모습이다.

```
브라우저 ── https ──> nginx (80/443) ──> gunicorn (127.0.0.1:8000) ──> Django
                        │                     └ systemd 유닛 jstocks
                        └ /static/ 는 nginx 가 직접 준다
```

- 서버 `cantoluna3` · 프로젝트 `/home/stock/jstocks`
- 도메인 `cantoluna3.cafe24.com` (Let's Encrypt 인증서)
- 8000 은 `127.0.0.1` 만 듣는다. 바깥에서 평문으로 들어올 길이 없다

HTTPS 를 처음 붙이는 순서는 [nginx-tls.md](./nginx-tls.md) 에 따로 적었다.

---

## 평소 배포 (코드만 바뀔 때)

```bash
cd /home/stock/jstocks
git pull
systemctl restart jstocks
```

마이그레이션이 생겼으면 재시작 전에 돌린다. **`makemigrations` 는 상용에서
돌리지 않는다** — 로컬에서 만들어 커밋하고 여기서는 적용만 한다. 그러지 않으면
번호가 갈라진다.

```bash
venv/bin/python manage.py migrate
```

패키지가 늘었으면,

```bash
venv/bin/pip install -r requirements.txt
```

화면의 CSS·JS(admin) 가 바뀌었으면,

```bash
venv/bin/python manage.py collectstatic --noinput
```

확인은 바깥에서 한다. 서버 안에서 `curl 127.0.0.1:8000` 은 nginx 를 건너뛰므로
반쪽만 본다.

```bash
curl -I https://cantoluna3.cafe24.com/ontoo/      # 200
systemctl status jstocks --no-pager | head -5
```

---

## 처음 세울 때

### 1. 코드와 가상환경

```bash
git clone <repository-url> jstocks
cd jstocks
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

### 2. Playwright 브라우저

공시 수집(`save_gongsi_stock`)과 노다지(`save_nodaji_stock`)가 크롬을 띄워
화면을 긁는다. **`requirements.txt` 로는 브라우저 바이너리가 설치되지 않는다.**

```bash
venv/bin/python -m playwright install --with-deps chromium
```

전에 이것 때문에 공시가 두 달 동안 한 건도 안 들어왔다. playwright 패키지가
올라가면 새 브라우저를 다시 받아야 하는데 그것을 안 했다. 패키지를 올린 뒤에는
이 명령을 같이 돌린다.

### 3. `.env`

프로젝트 루트(`/home/stock/jstocks/.env`)에 둔다. python-decouple 이 이 파일을
직접 읽는다 — systemd 유닛의 `EnvironmentFile` 로 넣지 않는다. 그렇게 하면
systemd 가 같은 파일을 제 방식으로 파싱해 환경변수로 올리고, decouple 은
환경변수를 먼저 보기 때문에 `SECRET_KEY` 같은 값이 조용히 달라질 수 있다.

```bash
# Django
SECRET_KEY=                      # manage.py 로 만든다 (아래)
DEBUG=False
ALLOWED_HOSTS=cantoluna3.cafe24.com,175.126.73.5,localhost,127.0.0.1

# nginx 뒤에서 (nginx-tls.md 5단계)
BEHIND_TLS_PROXY=True
CSRF_TRUSTED_ORIGINS=https://cantoluna3.cafe24.com
SECURE_COOKIES=True

# 로그인 시도 제한 (기본값이 있으므로 없어도 된다)
AXES_FAILURE_LIMIT=10
AXES_COOLOFF_HOURS=1

# 키움 — 주계좌
APPKEY=
SECRETKEY=

# 키움 — 계좌를 더 쓰면 접미사를 붙인다 (Account.key 와 같은 이름)
#   APPKEY_SUB1 / SECRETKEY_SUB1  ->  토큰은 token_sub1.json 에 저장된다
APPKEY_SUB1=
SECRETKEY_SUB1=

# 텔레그램 — 배치 알림 (봇)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# 텔레그램 — 채널 읽기 (사용자 계정, telethon)
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
```

DART 는 키가 필요 없다. 뷰어 페이지를 User-Agent 만 붙여 읽는다.

`SECRET_KEY` 는 손으로 만들지 않는다 — 추측 가능한 값은 키가 아니다.

```bash
venv/bin/python -c "import secrets; print(secrets.token_urlsafe(64))"
```

`ALLOWED_HOSTS` 가 한 줄만 있는지 확인한다. 같은 이름이 두 줄이면 뒤에 나온
줄이 이기므로, 위를 고치고 아래를 못 보면 안 바뀐 것처럼 보인다.

```bash
grep -c "^ALLOWED_HOSTS=" .env     # 1 이어야 한다
```

### 4. DB 와 정적 파일

```bash
venv/bin/python manage.py migrate
venv/bin/python manage.py collectstatic --noinput
venv/bin/python manage.py createsuperuser
```

### 5. systemd

유닛은 `/etc/systemd/system/jstocks.service` 에 있다. 레포에는 두지 않는다 —
예전에 레포의 사본이 실제와 달라(경로가 `/home/stock` 이었다) 그것을 보고
배포하면 뜨지 않는 상태로 한동안 있었다. 지금 돌고 있는 것이 기준이다.

```bash
systemctl cat jstocks
```

바깥에 노출하지 않는 설정은 drop-in 으로 얹는다.

```bash
mkdir -p /etc/systemd/system/jstocks.service.d
cp deploy/systemd/jstocks-bind.conf /etc/systemd/system/jstocks.service.d/bind.conf
systemctl daemon-reload && systemctl restart jstocks
```

### 6. nginx 와 HTTPS

[nginx-tls.md](./nginx-tls.md) 를 순서대로 따른다. 순서를 바꾸면 — 쿠키를 먼저
https 전용으로 돌리면 — 인증서가 붙기 전에 로그인이 막힌다.

### 7. 첫 데이터

```bash
venv/bin/python manage.py get_token
venv/bin/python manage.py save_stock_list --log-level info
venv/bin/python manage.py save_stock_info --code all --log-level info
```

나머지는 [commands.md](./commands.md) 에 있다.

---

## 배치 (cron)

세 개가 돈다. 실패를 알리는 장치는 `batch_lib.sh` 하나에 있고 셋이 같이 쓴다 —
걸린 단계의 이름과 원인을 텔레그램에 실어 보낸다.

```
40 15 * * 1-5  /home/stock/jstocks/daily_update.sh  >> logs/daily_update.log 2>&1
40 19 * * 1-5  /home/stock/jstocks/daum_update.sh   >> logs/daum_update.log 2>&1
0  23 * * 5    /home/stock/jstocks/weekly_update.sh >> logs/weekly_update.log 2>&1
```

```bash
crontab -l                       # 실제로 이렇게 걸려 있는지
ls -l *.sh                       # 실행 권한(+x)이 있어야 cron 이 돌린다
```

`batch_lib.sh` 는 `source` 로 읽히므로 실행 권한이 없어도 된다.

---

## 접근 경로

```
https://cantoluna3.cafe24.com/          내 화면 (로그인)
https://cantoluna3.cafe24.com/ontoo/    같이 보는 공유 페이지 (로그인 없음)
```

로그인 없이 열리는 곳은 `/login/` 과 `/ontoo/` 둘뿐이다. admin 도 `/login/` 을
먼저 지나야 열린다 (`stocks/middleware.py`).

---

## 문제 해결

### 공시가 안 들어온다

대개 크롬 바이너리다. 조용히 실패하지 않도록 고쳐 두었으니 로그 끝에
"한 건도 받지 못했습니다" 가 찍힌다.

```bash
venv/bin/python -m playwright install chromium
venv/bin/python manage.py save_gongsi_stock --code fav --log-level info
```

### 로그인이 잠겼다

열 번 틀리면 한 시간 잠긴다. 기다리지 않으려면 서버에서 푼다.

```bash
venv/bin/python manage.py axes_list_attempts
venv/bin/python manage.py axes_reset              # 전부
venv/bin/python manage.py axes_reset_ip 1.2.3.4   # 하나만
```

### 400 Bad Request 가 뜬다

`ALLOWED_HOSTS` 에 그 주소가 없다. 도메인으로 들어왔는데 IP 만 적혀 있는 경우다.

### 로그인은 되는데 저장이 403 (CSRF)

주소에 `:8000` 을 붙여 들어왔을 가능성이 높다. 그러면 nginx 를 건너뛰어 평문이
되고, 쿠키에 붙은 `Secure` 때문에 브라우저가 CSRF 쿠키를 보내지 않는다.
`https://cantoluna3.cafe24.com` 으로 들어온다.

그게 아니면 `.env` 의 `CSRF_TRUSTED_ORIGINS` 를 본다. 스킴(`https://`)까지
적어야 한다.

### 인증서가 곧 만료된다

자동 갱신이 돈다. 멈춰 있는지 본다.

```bash
systemctl list-timers | grep certbot
certbot renew --dry-run
```

### 화면이 CSS 없이 맨몸으로 보인다

admin 화면이면 `collectstatic` 을 안 돌린 것이다.

```bash
venv/bin/python manage.py collectstatic --noinput
curl -I https://cantoluna3.cafe24.com/static/admin/css/base.css   # 200
```

### 되돌리기

```bash
git log --oneline -5
git checkout <커밋>              # 코드만. 마이그레이션은 따로 되돌려야 한다
systemctl restart jstocks
```
