# 맥에서 도는 AI 시황 판단

상용 서버에서는 `claude` 바이너리가 뜨지 않는다.

```
error: this CPU is missing SSE4.2 support, which Bun requires.
```

게스트 CPU 가 `QEMU Virtual CPU version (cpu64-rhel6)` 으로 노출되어
`sse4_2` 플래그가 없다. 하이퍼바이저가 가리는 것이라 상품 사양을 올려도
CPU 모델은 그대로다. 메모리도 968Mi 로 공식 요구사항(4GB)에 못 미친다.

그래서 **부르는 일만 맥에서** 하고 나머지는 서버가 한다.

```
맥 (평일 20:20, launchd + pmset 예약 기상)
  ├ ssh jstocks  run_ai_note --list-pending    무엇이 필요한가
  ├ ssh jstocks  run_ai_note --emit-prompt     프롬프트를 받아
  ├ claude -p                                  맥에서 부르고
  └ ssh jstocks  run_ai_note --save-answer     서버에 저장
```

프롬프트를 만들고 답을 파싱해 저장하는 일은 전부 서버에 남는다. 맥은
부르기만 한다.

## 맥이 서버를 지켜보기도 한다

AI 판단보다 이쪽이 더 값어치 있을 수 있다.

서버의 배치는 실패하면 스스로 텔레그램을 보낸다. 그런데 **아예 안 돌면**
보낼 주체가 없다 — cron 이 멈췄거나, 재부팅 뒤 안 올라왔거나, 서버가
꺼졌거나. 그 조용함은 '정상' 과 구분되지 않는다. 공시가 두 달, 수급이
석 달, ETF 가 넉 달 조용했던 것이 전부 그 모양이었다.

감시자가 감시 대상에 기대면 안 된다. 맥은 **다른 기계, 다른 스케줄러**다.
20:20 에 세 가지를 본다.

| 보는 것 | 못 보면 |
|---|---|
| `ssh` 가 붙는가 | `⚠️ 서버에 붙지 못했습니다` |
| 저녁 배치·DB 백업이 오늘 돌았는가 | `⚠️ 서버 배치가 돌지 않았습니다` |
| 데이터가 신선한가 (`check_freshness`) | `⚠️ 데이터가 신선하지 않습니다` |

**텔레그램을 맥에서 직접 보낸다.** 서버를 거치면 서버가 죽었을 때 알릴
길도 같이 죽는다. 그래서 봇 토큰을 맥에도 둔다.

```bash
umask 077
ssh jstocks 'cd /home/stock/jstocks && grep -E "^TELEGRAM_(BOT_TOKEN|CHAT_ID)=" .env' \
    > ~/jstocks-ainote/telegram.env
chmod 600 ~/jstocks-ainote/telegram.env
```

맥에는 이미 서버로 드는 SSH 키가 있으므로 비밀이 하나 더 는다고 크게
달라지지 않는다.

### 배치가 돌았는지 어떻게 아나

로그에 오늘 날짜의 `완료:` 줄이 있는지 본다. `batch_lib.sh` 가 끝에
`<라벨> 업데이트 완료: YYYY-MM-DD HH:MM:SS` 를 찍는다.

**파일 수정시각은 보지 않는다.** logrotate 가 `copytruncate` 로 비우면서
시각을 건드려, 돌지 않았는데 방금 쓴 것처럼 보인다.

**`daily_update` 는 보지 않는다.** 휴장일이면 완료 줄을 찍기 전에 끝나
'안 돌았다' 와 구분되지 않는다. `evening_update` 는 휴장일에도 돌고
`backup_db` 는 주말에도 돈다 — 그 둘이면 충분하다.

### 남는 구멍

맥도 같이 죽으면 그때는 모른다. 다만 서로 다른 두 기계가 동시에 조용히
죽을 확률은 하나가 죽을 확률보다 훨씬 낮다.

## 세울 때

### 1. SSH 키 (맥 → 서버)

root 가 아니라 앱 계정 `stock` 으로 붙는다. 실행할 명령이 전부 그 권한이다.

```bash
# 맥에서
ssh-keygen -t ed25519 -C "jstocks-ai-note" -f ~/.ssh/id_jstocks_ainote -N ""
cat ~/.ssh/id_jstocks_ainote.pub
```

```bash
# 서버에서 (공개키를 붙여 넣는다)
install -d -m 700 -o stock -g stock /home/stock/.ssh
cat >> /home/stock/.ssh/authorized_keys <<'KEY'
no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-user-rc ssh-ed25519 AAAA... jstocks-ai-note
KEY
chown stock:stock /home/stock/.ssh/authorized_keys
chmod 600 /home/stock/.ssh/authorized_keys
```

맥의 `~/.ssh/config` 에 별칭을 둔다. 스크립트가 `jstocks` 로 부른다.

```
Host jstocks
    HostName 175.126.73.5
    User stock
    IdentityFile ~/.ssh/id_jstocks_ainote
    IdentitiesOnly yes
    BatchMode yes          # 무인 실행이라 물어보면 멈춘다
    ConnectTimeout 15
    ServerAliveInterval 30
```

```bash
ssh jstocks 'echo OK'
```

### 2. 스크립트와 launchd

```bash
mkdir -p ~/jstocks-ainote
cp deploy/mac/ainote-run.sh ~/jstocks-ainote/run.sh
chmod +x ~/jstocks-ainote/run.sh

sed "s|REPLACE_HOME|$HOME|g" deploy/mac/com.jstocks.ainote.plist \
    > ~/Library/LaunchAgents/com.jstocks.ainote.plist

launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.jstocks.ainote.plist
```

### 3. 예약 기상

```bash
sudo pmset repeat wakeorpoweron MTWRF 20:20:00
pmset -g sched
```

## 왜 20:20 인가

서버의 `evening_update.sh` 가 19:40 에 돈다. 그 배치의 1·2단계(시장 동향,
시장 지표)가 2~3분 안에 끝나고, 시황 판단이 읽는 것이 그 둘이다. 20:20 이면 넉넉하다. 뒤따르는
80종목 수급은 시황과 무관하므로 기다릴 것 없다.

## 기상 시각과 실행 시각은 같은 분이어야 한다

여기서 한 번 틀렸다. 기상을 20:20 에, 실행을 20:21 에 걸면 돌지 않는다.

뚜껑 닫힌 맥북은 예약 기상 뒤 붙잡는 것이 없으면 **10초 만에** 도로 잠든다.
실측한 기록이다.

```
19:52:15  Sleep          뚜껑 닫아 잠듦
19:56:00  Wake           예약 기상 (pmset)
19:56:10  DarkWake 진입   ← 10초
19:56:45  Sleep          완전히 다시 잠듦
          ⋮              19:57 작업은 뜰 틈이 없었다
```

같은 분에 걸어 그 창 안에 작업이 떠서 `caffeinate -i -s` 로 붙잡아야 한다.
`-s` 는 시스템 절전을 막지만 AC 전원일 때만 들고, `-i` 는 배터리에서도
유휴 절전만은 막는다. 둘 다 건다.

## 맥 상태별로 어떻게 되나

| 그 시각 맥 | 결과 |
|---|---|
| 쓰고 있음 | 백그라운드로 그냥 실행 |
| 클램셸 (모니터 연결 + 뚜껑 닫힘) | 그냥 실행 |
| 잠들어 있음 | 예약 기상으로 깨서 실행 |
| 예약 기상이 안 먹음 | 다음에 깨울 때 **밀린 작업으로** 실행 (`cron` 은 건너뛴다) |
| 전원 꺼짐 | 안 됨. 켤 때 밀린 작업으로 실행 |

하루에 여러 번 돌아도 토큰을 두 번 쓰지 않는다. `--list-pending` 이 이미
판단이 있는 것은 빼고 준다.

## 확인

```bash
cat ~/jstocks-ainote/run.log        # 실행 기록
launchctl print gui/$UID/com.jstocks.ainote | grep -E 'state|runs'
~/jstocks-ainote/run.sh             # 손으로 한 번
```

## 걷어낼 때

```bash
launchctl bootout gui/$UID/com.jstocks.ainote
rm ~/Library/LaunchAgents/com.jstocks.ainote.plist
rm -rf ~/jstocks-ainote
sudo pmset repeat cancel
```
