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
맥 (평일 20:00, launchd + pmset 예약 기상)
  ├ ssh jstocks  run_ai_note --list-pending    무엇이 필요한가
  ├ ssh jstocks  run_ai_note --emit-prompt     프롬프트를 받아
  ├ claude -p                                  맥에서 부르고
  └ ssh jstocks  run_ai_note --save-answer     서버에 저장
```

프롬프트를 만들고 답을 파싱해 저장하는 일은 전부 서버에 남는다. 맥은
부르기만 한다. 실패하면 서버를 거쳐 텔레그램으로 알린다 — 배치 알림과
같은 통로다.

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
sudo pmset repeat wakeorpoweron MTWRF 20:00:00
pmset -g sched
```

## 왜 20:00 인가

서버의 `evening_update.sh` 가 19:40 에 돈다. 그 배치의 1·2단계(시장 동향,
시장 지표)가 2~3분 안에 끝나고, 시황 판단이 읽는 것이 그 둘이다. 뒤따르는
80종목 수급은 시황과 무관하므로 기다릴 것 없다.

## 기상 시각과 실행 시각은 같은 분이어야 한다

여기서 한 번 틀렸다. 기상을 20:00 에, 실행을 20:01 에 걸면 돌지 않는다.

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
