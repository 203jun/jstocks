# run_ai_note

사람이 하던 복사·붙여넣기를 대신한다. 화면의 [프롬프트] 버튼이 만드는 것과
똑같은 글을 서버에서 만들어 Claude 에 보내고, 돌아온 답을 `AiNote` 에 넣는다.

```
build_market_panel()      지표를 읽고
get_prompt()              설정에서 고친 템플릿을 꺼내고
build_prompt_vars()       {지표} {상태변화} 를 채우고
  ↓
claude -p                 ← 사람이 claude.ai 에 붙여넣던 자리
  ↓
ai_note.parse()           한 줄 결론과 매매 스탠스를 뽑아
AiNote.update_or_create() 기준일로 저장한다
```

클립보드도 브라우저도 끼지 않는다. 그 둘은 사람이 중간에 있을 때만 필요한
부품이다.

## 사용법

바깥에서 Claude 를 부를 때는 세 토막으로 나눠 쓴다.

```bash
python manage.py run_ai_note --list-pending
# market KOSPI 2026-11-13
# market KOSDAQ 2026-11-13

python manage.py run_ai_note --key KOSPI --emit-prompt > 프롬프트.txt
claude -p --allowedTools WebSearch < 프롬프트.txt > 답.txt
python manage.py run_ai_note --key KOSPI --basis 2026-11-13 --save-answer < 답.txt
```

서버에서 직접 부를 때 (이 서버에서는 CPU 때문에 못 쓴다):

```bash
# 프롬프트만 보고 (부르지 않는다)
python manage.py run_ai_note --key KOSPI --dry-run

# 한 시장만, 답을 화면에 찍으면서
python manage.py run_ai_note --key KOSPI --show

# 코스피·코스닥 둘 다 (배치용)
python manage.py run_ai_note
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--kind` | X | 지금은 `market` 만 (기본: market) |
| `--key` | X | KOSPI / KOSDAQ / all (기본: all) |
| `--force` | X | 같은 기준일에 판단이 있어도 다시 받는다 |
| `--dry-run` | X | 프롬프트만 찍고 부르지 않는다 |
| `--show` | X | 받은 답을 전부 찍는다 |
| `--log-level` | X | debug / info / warning / error (기본: info) |
| `--list-pending` | X | 판단이 필요한 대상을 `자리 대상 기준일` 로 출력 |
| `--emit-prompt` | X | 프롬프트만 stdout 으로 (부르지 않는다) |
| `--save-answer` | X | stdin 으로 받은 답을 파싱해 저장 |
| `--basis` | X | 기준일 YYYY-MM-DD. `--save-answer` 와 함께 |

## 기준일

저장한 날이 아니라 **판단의 근거가 된 데이터의 날짜**다. 토요일에 돌려도
데이터는 금요일 것이라 저장일로 잡으면 어긋난다. 화면에서 사람이 저장할
때(`views.ai_note_save`)와 같은 값을 쓴다.

같은 기준일에 판단이 이미 있으면 **건너뛴다**. 배치가 두 번 돌아도 토큰을
두 번 쓰지 않는다. 다시 받으려면 `--force`.

## 이 서버에서는 claude 가 돌지 않는다

```
error: this CPU is missing SSE4.2 support, which Bun requires.
```

상용 서버의 게스트 CPU 가 `QEMU Virtual CPU version (cpu64-rhel6)` 으로
노출된다. 하이퍼바이저가 기능을 가리고 있어 `sse4_2` 플래그가 없다.
claude 바이너리(Bun 기반)가 그것을 요구한다. 상품 사양을 올려도 CPU 모델은
그대로이므로 해결되지 않는다. 메모리도 968Mi 로 공식 요구사항(4GB)에 못
미친다.

그래서 **부르는 일만 맥에서** 하고 나머지는 서버에서 한다.

```
맥 (평일 20:20, launchd + pmset 예약 기상)
  ├ ssh jstocks  run_ai_note --list-pending      무엇이 필요한가
  ├ ssh jstocks  run_ai_note --emit-prompt       프롬프트를 받아
  ├ claude -p                                    맥에서 부르고
  └ ssh jstocks  run_ai_note --save-answer       서버에 저장
```

프롬프트를 만들고 답을 파싱해 저장하는 일은 전부 서버가 한다. 맥은 부르기만
한다. 세 토막 모두 stdout 으로는 주고받는 내용만 내보내고 로그는 stderr 로
보낸다 — 받는 쪽이 둘을 구분하지 못하면 프롬프트에 로그가 섞인다.

### 기준일을 들고 다니는 까닭

프롬프트를 뽑은 뒤 답을 저장하기까지 몇 분이 걸린다. 그사이 새 데이터가
들어오면 기준일이 바뀌고, 옛 데이터로 내린 판단이 새 날짜에 붙는다.
`--list-pending` 이 기준일을 함께 주고 `--save-answer` 가 `--basis` 로
받아, 뽑을 때의 날짜에 저장한다.

### 맥이 잠들어 있어도 되는가

된다. 다만 **예약 기상 시각과 실행 시각이 같은 분이어야 한다.**

뚜껑이 닫힌 맥북은 예약 기상 뒤 붙잡는 것이 없으면 **10초 만에** 도로
잠든다(실측). 1분 뒤에 작업을 걸면 그때는 이미 자고 있어 뜨지 못한다.
같은 분에 걸어 그 창 안에 떠서 `caffeinate -i -s` 로 붙잡아야 한다.

맥이 깨어 있거나 클램셸이면 그냥 돈다. 예약 기상이 실패해도 `launchd` 는
다음에 깨울 때 밀린 작업을 실행한다(`cron` 은 건너뛴다).

## 왜 API 가 아니라 CLI 인가

구독으로 돌아 호출마다 돈이 나가지 않는다. 대신 인증이 사람 계정에 묶여
있어 언젠가 끊긴다.

claude.ai 를 브라우저로 자동 조작하는 길도 있지만 이용약관이 자동화된
접근을 막는다. 계정이 정지되면 아끼려던 것보다 잃는 것이 크다. 헤드리스
CLI 는 그 용도로 만들어진 것이라 괜찮다.

## 인증이 끊기면

리프레시 토큰은 몇 달을 가지만 비밀번호 변경·다른 기기에서 전체 로그아웃·
구독 변경이 있으면 그날로 끊긴다. 날짜를 예측할 수 없다.

그래서 배치 맨 앞에 확인용 호출을 하나 둔다.

```bash
python manage.py check_claude_auth
```

끊겨 있으면 종료코드 1 로 끝나고 `batch_lib.sh` 가 텔레그램을 보낸다.
80종목을 다 돌린 뒤에 아는 것보다 맨 앞에서 아는 편이 낫다. 복구는
서버에서 한 줄이다.

```bash
sudo -u stock claude login
```

## 토큰과 한도

`claude -p` 는 호출마다 Claude Code 의 시스템 프롬프트와 툴 정의(약 1만
토큰)를 같이 보낸다. 구독이면 돈은 안 나가지만 **사용량 한도에는 잡힌다.**

다만 그 부분은 1시간 동안 캐시된다. **한 배치에서 연달아** 돌리면 첫 건만
제값을 내고 나머지는 캐시를 읽는다. 띄엄띄엄 돌리면 매번 새로 만든다.
종목 단위(80개)로 넓힐 때 이것이 설계를 가른다.

## 열어 둔 툴

`WebSearch` 하나만 연다. 프롬프트에 "웹 검색을 사용해 기준일의 시장 뉴스를
확인하라" 가 적혀 있다 — 사람이 claude.ai 에 붙여넣을 때는 검색이 되므로,
막아 두면 '오늘 움직임' 섹션이 통째로 빠져 사람이 하던 것보다 못한 답이
나온다.

파일 읽기와 명령 실행은 막는다. 빈 디렉터리에서 돌려 `CLAUDE.md` 와 둘레
파일도 읽지 않게 한다 — 날마다 쌓아 견주는 판단에 그런 것이 섞이면 안 된다.

## 저장 모델

`AiNote` (kind=`market`, key=`KOSPI`/`KOSDAQ`)

## 실행 주기

서버 배치에는 넣지 않는다 — 여기서는 claude 가 돌지 않는다.
맥에서 평일 20:20 에 돈다. `evening_update.sh`(19:40)의 시장 동향·시장
지표가 그 전에 끝난다. 대상은 코스피·코스닥 시황 둘뿐이다.
