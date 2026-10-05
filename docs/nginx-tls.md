# nginx + HTTPS 붙이기

지금은 gunicorn 이 `0.0.0.0:8000` 에 그대로 떠 있고 평문이다. `/ontoo/` 링크를
뿌리면 주소가 알려지는데, 그 상태로는 **내가 로그인할 때 비밀번호가 평문으로
네트워크에 흐른다.** 동료는 읽기만 하니 상관없고, 위험은 내 계정에 있다.

**순서가 중요하다.** 쿠키를 먼저 https 전용으로 바꾸면 인증서가 붙기 전에
로그인이 막힌다. 아래 순서대로 한다. 각 단계에 확인 명령이 있고, 그것이
통과한 뒤에 다음으로 넘어간다.

---

## 0. 준비 확인

```bash
dig +short YOUR_DOMAIN          # 175.126.73.5 가 나와야 한다
```

도메인이 이 서버를 가리키지 않으면 인증서 발급이 실패한다. 80 포트도 열려
있어야 한다 (certbot 이 그 포트로 소유를 확인한다).

---

## 1. 설치

```bash
apt update
apt install -y nginx certbot python3-certbot-nginx
```

---

## 2. 사이트 올리기 (아직 http 만)

```bash
cd /home/stock/jstocks
git pull

cp deploy/nginx/jstocks.conf /etc/nginx/sites-available/jstocks
sed -i 's/YOUR_DOMAIN/실제도메인/g' /etc/nginx/sites-available/jstocks

ln -sf /etc/nginx/sites-available/jstocks /etc/nginx/sites-enabled/jstocks
rm -f /etc/nginx/sites-enabled/default      # 기본 사이트가 요청을 먹는 일이 있다

nginx -t                                     # 통과해야 다음으로 간다
systemctl reload nginx

curl -I http://실제도메인/ontoo/              # 200
```

여기까지는 평문이다. 아직 Django 설정도 안 바꿨으니 되돌릴 것도 없다.

---

## 3. 인증서 발급 — certbot 이 TLS 를 써 넣는다

```bash
certbot --nginx -d 실제도메인
```

certbot 이 위 파일에 443 블록, 인증서 경로, http→https 리다이렉트를 **그 서버의
nginx 버전에 맞게** 직접 써 넣는다. 그래서 설정 파일에 443 을 미리 적지 않았다.

```bash
curl -I https://실제도메인/ontoo/            # 200
curl -I http://실제도메인/ontoo/             # 301 -> https
```

갱신은 `certbot.timer` 가 자동으로 돈다.

```bash
systemctl list-timers | grep certbot
certbot renew --dry-run
```

---

## 4. 정적 파일 모으기

admin 화면의 CSS·JS 자리다. 그동안 아무것도 서빙하지 않아 admin 이 맨몸으로
보였다.

```bash
cd /home/stock/jstocks
venv/bin/python manage.py collectstatic --noinput
curl -I https://실제도메인/static/admin/css/base.css     # 200
```

---

## 5. Django 설정 켜기 — 인증서가 뜬 것을 확인한 뒤에

`/home/stock/jstocks/.env` 를 고친다. `ALLOWED_HOSTS` 에 도메인을 **반드시**
넣는다 — 없으면 Django 가 전부 400 으로 끊는다.

```
ALLOWED_HOSTS=실제도메인,175.126.73.5,localhost,127.0.0.1
BEHIND_TLS_PROXY=True
CSRF_TRUSTED_ORIGINS=https://실제도메인
SECURE_COOKIES=True
```

```bash
systemctl restart jstocks
```

확인 — 로그인해서 **메모를 저장해 본다.** CSRF 가 틀어지면 여기서 걸린다.
`/ontoo/` 도 열어 본다.

---

## 6. 8000 포트 닫기

여기까지면 https 로 들어온다. 그런데 8000 이 아직 열려 있어 평문으로 건너뛸
수 있다. 그러면 인증서를 붙인 뜻이 없다.

```bash
systemctl cat jstocks            # 지금 돌고 있는 것을 먼저 본다
cat deploy/jstocks.service       # 새로 쓸 것
```

**두 파일의 경로(WorkingDirectory·EnvironmentFile)를 비교하고 맞는지 확인한
뒤에** 바꾼다. 레포에 있던 옛 유닛은 경로가 실제와 달랐다.

```bash
cp deploy/jstocks.service /etc/systemd/system/jstocks.service
systemctl daemon-reload
systemctl restart jstocks
systemctl status jstocks --no-pager

curl -I http://127.0.0.1:8000/ontoo/       # 200 (서버 안에서는 된다)
curl -I http://175.126.73.5:8000/ontoo/    # 안 되어야 한다
```

방화벽에서도 막는다. **22 번을 먼저 허용하고** ufw 를 켠다 — 순서를 바꾸면
ssh 가 끊긴다.

```bash
ufw allow 22
ufw allow 80
ufw allow 443
ufw deny 8000
ufw enable
ufw status
```

---

## 7. 되돌리기

못 들어오게 되면 `.env` 의 세 줄(`BEHIND_TLS_PROXY`, `CSRF_TRUSTED_ORIGINS`,
`SECURE_COOKIES`)을 지우고 재시작하면 평문 상태로 돌아온다. 유닛을 바꿨다면
`--bind 0.0.0.0:8000` 으로 되돌린다.

```bash
systemctl restart jstocks
```

---

## 남는 것

- **로그인 시도 제한** — `/login/` 과 `/admin/login/` 에 무제한으로 시도할 수
  있다. 내 IP 만 허용하는 방법을 `deploy/nginx/jstocks.conf` 아래쪽에 주석으로
  적어 두었다. IP 가 바뀌는 회선이면 쓰지 않는다.
- **SECRET_KEY 교체** — 한 번 외부에 보인 적이 있다. 바꾸면 세션이 끊겨 다시
  로그인하는 것이 전부다.
- **/ontoo/ 는 그대로 열어 둔다.** 동료가 보는 자리다. https 가 되면 주소만
  `https://실제도메인/ontoo/` 로 바뀐다.
