# nginx + HTTPS 붙이기

지금은 gunicorn 이 `0.0.0.0:8000` 에 그대로 떠 있고 평문이다. `/ontoo/` 링크를
뿌리면 주소가 알려지는데, 그 상태로는 **내가 로그인할 때 비밀번호가 평문으로
네트워크에 흐른다.** 동료는 읽기만 하니 상관없고, 위험은 내 계정에 있다.

**순서가 중요하다.** 쿠키를 먼저 https 전용으로 바꾸면 인증서가 붙기 전에
로그인이 막힌다. 아래 순서대로 한다. 각 단계에 확인 명령이 있고, 그것이
통과한 뒤에 다음으로 넘어간다.

---

## 0. 준비 확인 — 여기서 걸릴 만한 것이 둘 있다

도메인은 카페24 기본 호스트네임을 쓴다. 조회해 보면 이 서버를 가리킨다.

```bash
dig +short cantoluna3.cafe24.com          # 175.126.73.5
```

### (1) 80 · 443 이 바깥에서 닿아야 한다

바깥에서 재 보니 둘 다 응답이 없었다. 아무것도 안 듣고 있는 것인지, 카페24
쪽에서 막은 것인지를 먼저 가른다. 앞이면 nginx 를 띄우면 되고, **뒤면
certbot 의 HTTP-01 방식으로는 인증서를 받을 수 없다.**

```bash
ss -lntp | grep -E ':80|:443'     # 아무것도 없으면 '안 듣는 중'
ufw status                         # 서버 방화벽
iptables -L INPUT -n | head -20
```

서버에서는 아무것도 안 막고 있는데 바깥에서 안 닿으면 카페24 쪽 차단이다.
그 경우는 호스팅 설정이나 고객센터에서 80·443 인바운드를 열어야 한다.

### (2) 발급 한도 — 이름이 남의 것과 같은 지붕 아래 있다

`cafe24.com` 은 Public Suffix List 에 없다. 그래서 Let's Encrypt 는 발급 한도를
`cafe24.com` 하나로 묶어 센다 — 카페24 고객 누군가가 그 주를 다 써 버렸으면
내 발급도 거절된다 ("too many certificates already issued for: cafe24.com").

그래서 **먼저 연습 발급으로 길을 확인한다.**

```bash
certbot certonly --nginx -d cantoluna3.cafe24.com --dry-run
```

연습은 다른 서버(staging)를 쓰고 한도가 느슨하다. 즉 **연습이 되는 것은
'설정과 80 포트가 맞다' 는 뜻이고, 실제 발급의 한도까지 보장하지는 않는다.**
실제 발급에서 한도로 막히면 아래 '한도에 막혔을 때' 로 간다.

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

ln -sf /etc/nginx/sites-available/jstocks /etc/nginx/sites-enabled/jstocks
rm -f /etc/nginx/sites-enabled/default      # 기본 사이트가 요청을 먹는 일이 있다

nginx -t                                     # 통과해야 다음으로 간다
systemctl reload nginx

curl -I http://cantoluna3.cafe24.com/ontoo/              # 200
```

여기까지는 평문이다. 아직 Django 설정도 안 바꿨으니 되돌릴 것도 없다.

---

## 3. 인증서 발급 — certbot 이 TLS 를 써 넣는다

```bash
certbot --nginx -d cantoluna3.cafe24.com
```

certbot 이 위 파일에 443 블록, 인증서 경로, http→https 리다이렉트를 **그 서버의
nginx 버전에 맞게** 직접 써 넣는다. 그래서 설정 파일에 443 을 미리 적지 않았다.

```bash
curl -I https://cantoluna3.cafe24.com/ontoo/            # 200
curl -I http://cantoluna3.cafe24.com/ontoo/             # 301 -> https
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
curl -I https://cantoluna3.cafe24.com/static/admin/css/base.css     # 200
```

---

## 5. Django 설정 켜기 — 인증서가 뜬 것을 확인한 뒤에

`/home/stock/jstocks/.env` 를 고친다. `ALLOWED_HOSTS` 에 도메인을 **반드시**
넣는다 — 없으면 Django 가 전부 400 으로 끊는다.

```
ALLOWED_HOSTS=cantoluna3.cafe24.com,175.126.73.5,localhost,127.0.0.1
BEHIND_TLS_PROXY=True
CSRF_TRUSTED_ORIGINS=https://cantoluna3.cafe24.com
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
수 있다. 그러면 인증서를 붙인 뜻이 없고, 실제로 사고가 난다 — :8000 으로
들어가면 쿠키의 Secure 때문에 브라우저가 CSRF 쿠키를 안 보내 로그인이 막힌다.

유닛 파일은 덮어쓰지 않는다. ExecStart 하나만 drop-in 으로 바꾼다.

```bash
cd /home/stock/jstocks
systemctl cat jstocks | grep -E "WorkingDirectory|EnvironmentFile|ExecStart"
```

원본에 **EnvironmentFile 이 없는 것이 정상이다.** 환경변수는 python-decouple 이
.env 를 직접 읽는다. 여기에 EnvironmentFile 을 더하면 systemd 도 같은 파일을
파싱해 환경변수로 넣고, decouple 은 환경변수를 먼저 본다. SECRET_KEY 에
`$ % ! ^ @ )` 가 섞여 있어 systemd 가 다르게 해석하면 키가 조용히 달라진다 —
세션이 전부 깨진다. 그래서 건드리지 않는다.

```bash
mkdir -p /etc/systemd/system/jstocks.service.d
cp deploy/systemd/jstocks-bind.conf /etc/systemd/system/jstocks.service.d/bind.conf

systemctl daemon-reload
systemctl restart jstocks
systemctl status jstocks --no-pager | head -5

# 바뀐 ExecStart 가 먹었는지
systemctl show jstocks -p ExecStart | tr ';' '\n' | grep -o '\-\-bind [^ ]*'
```

확인한다.

```bash
curl -I http://127.0.0.1:8000/ontoo/              # 200 (서버 안에서는 된다)
curl -I https://cantoluna3.cafe24.com/ontoo/      # 200
```

바깥에서 8000 이 막혔는지는 서버 안에서 알 수 없다. 다른 회선(휴대폰 등)에서
`http://175.126.73.5:8000/` 를 열어 **안 되는 것**을 확인한다.

방화벽에서도 막는다. **22 번을 먼저 허용하고** ufw 를 켠다 — 순서를 바꾸면
ssh 가 끊긴다.

```bash
ufw allow 22
ufw allow 80
ufw allow 443
ufw enable
ufw status
```

8000 은 이제 127.0.0.1 만 듣고 있으니 ufw 에서 따로 막을 것이 없다. 그래도
이중으로 두고 싶으면 `ufw deny 8000` 을 더한다.

---

## 7. 들어오는 문을 내 IP 만 열기

고정 IP 를 쓰므로 할 수 있다. 모르는 사람은 로그인 화면 자체를 못 본다.
HTTPS 를 붙이기 전이라도 이것만으로 상당히 줄어든다.

먼저 **내 접속 IP** 를 안다. 서버 IP(175.126.73.5)가 아니라, 내가 앉아 있는
쪽의 주소다.

```bash
# 내 PC 에서
curl ifconfig.me
```

`/etc/nginx/sites-available/jstocks` 아래쪽 주석을 풀고 YOUR_IP 를 그 값으로
바꾼다. `/ontoo/` 는 건드리지 않는다 — 동료가 보는 자리다.

```bash
nginx -t && systemctl reload nginx
```

확인 — 내 PC 에서는 로그인 화면이 뜨고, 휴대폰 LTE 처럼 다른 회선에서는
403 이 나와야 한다.

```bash
curl -I https://cantoluna3.cafe24.com/login/     # 내 PC: 200
                                                  # 다른 회선: 403
curl -I https://cantoluna3.cafe24.com/ontoo/     # 어디서나: 200
```

회선을 바꾸거나 IP 가 바뀌면 나도 못 들어온다. 그때는 서버에 ssh 로 들어가
그 두 location 을 다시 주석 처리하면 된다.

---

## 8. 되돌리기

못 들어오게 되면 `.env` 의 세 줄(`BEHIND_TLS_PROXY`, `CSRF_TRUSTED_ORIGINS`,
`SECURE_COOKIES`)을 지우고 재시작하면 평문 상태로 돌아온다.

```bash
systemctl restart jstocks
```

8000 을 다시 열려면 drop-in 을 지운다. 원본 유닛은 건드린 적이 없으므로 그대로
돌아온다.

```bash
rm -rf /etc/systemd/system/jstocks.service.d
systemctl daemon-reload && systemctl restart jstocks
```

---

## 한도에 막혔을 때

`cafe24.com` 한도로 거절되면 이름을 하나 더 두는 수밖에 없다.

- **무료 호스트네임** — DuckDNS 같은 곳에서 `아무이름.duckdns.org` 를 받아
  175.126.73.5 를 가리키게 한다. duckdns.org 는 Public Suffix List 에 있어서
  내 이름 몫의 한도를 따로 받는다. 동료에게 주는 주소가 그 이름으로 바뀐다.
- **IP 제한만으로 버티기** — HTTPS 를 미루고 아래 7 번만 한다. 고정 IP 가 있어
  할 수 있는 선택이고, 남는 위험은 내 회선에서 서버까지의 구간이다.

---

## 남는 것

- **로그인 시도 제한** — `/login/` 과 `/admin/login/` 에 무제한으로 시도할 수
  있다. 내 IP 만 허용하는 방법을 `deploy/nginx/jstocks.conf` 아래쪽에 주석으로
  적어 두었다. IP 가 바뀌는 회선이면 쓰지 않는다.
- **SECRET_KEY 교체** — 한 번 외부에 보인 적이 있다. 바꾸면 세션이 끊겨 다시
  로그인하는 것이 전부다.
- **/ontoo/ 는 그대로 열어 둔다.** 동료가 보는 자리다. https 가 되면 주소만
  `https://cantoluna3.cafe24.com/ontoo/` 로 바뀐다.
