#!/bin/bash
#
# AI 시황 판단 — 맥이 부르고 서버가 저장한다.
#
# 상용 서버에서는 claude 바이너리가 뜨지 않는다. 게스트 CPU 가
# cpu64-rhel6 으로 노출되어 SSE4.2 가 없고 Bun 이 그것을 요구한다.
# 그래서 부르는 일만 여기서 하고, 프롬프트를 만들고 답을 파싱해 저장하는
# 일은 전부 서버가 한다 (manage.py run_ai_note).
#
#   ssh jstocks  --list-pending     무엇이 필요한가
#   ssh jstocks  --emit-prompt      프롬프트를 받아
#   claude -p                       여기서 부르고
#   ssh jstocks  --save-answer      서버에 저장
#
# launchd 가 평일 20:20 에 부른다. 기상 예약도 같은 분이어야 한다 —
# 뚜껑 닫힌 맥북은 깨어난 뒤 붙잡는 것이 없으면 10초 만에 도로 잠든다.
#
# 손으로 돌려볼 때:  ~/jstocks-ainote/run.sh

set -uo pipefail

REMOTE=jstocks
APP='cd /home/stock/jstocks && venv/bin/python manage.py'
RUN="$APP run_ai_note"
LOG=~/jstocks-ainote/run.log
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

MODEL=claude-sonnet-5-5
# 검색만 연다. 프롬프트가 "웹 검색을 사용해 기준일의 시장 뉴스를 확인하라" 를
# 전제로 쓰여 있어, 막으면 '오늘 움직임' 섹션이 통째로 빠진다. 파일 읽기와
# 명령 실행은 막는다 — 여기서 시키는 일은 글을 읽고 글을 내놓는 것뿐이다.
TOOLS=WebSearch

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }

# 텔레그램은 맥에서 **직접** 보낸다. 서버를 거치지 않는다.
#
# 감시자가 감시 대상에 기대면 안 된다. 서버가 죽었을 때 그것을 알리는 것이
# 이 스크립트의 일인데, 알리는 길이 서버를 지나면 같이 죽는다.
#
# 그래서 봇 토큰을 맥에도 둔다(telegram.env, 600). 맥에는 이미 서버로 드는
# SSH 키가 있으므로 비밀이 하나 더 는다고 크게 달라지지 않는다.
TELEGRAM_ENV=$HOME/jstocks-ainote/telegram.env

notify() {
    if [ ! -r "$TELEGRAM_ENV" ]; then
        log "텔레그램 설정이 없다: $TELEGRAM_ENV"
        return
    fi
    # shellcheck disable=SC1090
    . "$TELEGRAM_ENV"
    curl -s -m 20 -o /dev/null \
        -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
        --data-urlencode "text=$1" \
        || log "텔레그램 전송 실패 (알림만 실패했고 작업은 계속한다)"
}

echo "────────────────────────────────────────" >> "$LOG"
log "시작 ($(date '+%Y-%m-%d %a'))"

# launchd 가 주는 PATH 는 /usr/bin:/bin:/usr/sbin:/sbin 뿐이다. plist 에서
# ~/.local/bin 을 넣어 두었지만, claude 가 업데이트로 자리를 옮기거나 지워질
# 수 있다. 없으면 여기서 알린다 — 안 그러면 날마다 조용히 실패한다.
CLAUDE=$(command -v claude || true)
if [ -z "$CLAUDE" ]; then
    log "claude 를 찾지 못했다 (PATH=$PATH)"
    notify "⚠️ AI 시황 판단 멈춤"$'\n\n'"맥에서 claude 를 찾지 못했습니다."$'\n'"PATH=$PATH"
    exit 1
fi
log "claude $("$CLAUDE" --version 2>/dev/null | head -1) ($CLAUDE)"

# ── 서버가 살아 있고 배치가 돌았는지 ──────────────────────────────────
#
# 서버의 배치는 실패하면 스스로 텔레그램을 보낸다. 그런데 **아예 안 돌면**
# 보낼 주체가 없다 — cron 이 멈췄거나, 재부팅 뒤 안 올라왔거나, 서버가
# 꺼졌거나. 그 조용함은 '정상' 과 구분되지 않는다.
#
# 맥은 다른 기계, 다른 스케줄러다. 여기서 대신 확인한다.

TODAY=$(date +%F)
MISSING=()

if ! ssh -o ConnectTimeout=20 "$REMOTE" true 2>>"$LOG"; then
    log "서버에 붙지 못했다"
    notify "⚠️ 서버에 붙지 못했습니다"$'\n\n'"$(date '+%m/%d %H:%M') · ssh jstocks 실패"$'\n'"서버가 꺼졌거나 네트워크가 끊겼을 수 있습니다."
    exit 1
fi

# 배치가 끝나면 batch_lib.sh 가 '<라벨> 업데이트 완료: YYYY-MM-DD ...' 를
# 로그에 찍는다. 오늘 날짜가 있는지만 본다.
#
# 파일 수정시각을 보지 않는 까닭: logrotate 가 copytruncate 로 비우면서
# 시각을 건드린다. 돌지 않았는데 방금 쓴 것처럼 보인다.
#
# daily_update 는 보지 않는다. 휴장일이면 완료 줄을 찍기 전에 끝나므로
# '안 돌았다' 와 구분되지 않는다. evening_update 는 휴장일에도 돌고
# backup_db 는 주말에도 돈다 — 그 둘이면 충분하다.
check_ran() {
    local logfile="$1" label="$2"
    if ssh "$REMOTE" "grep -q '완료: $TODAY' /home/stock/jstocks/logs/$logfile" 2>/dev/null; then
        log "   $label: 오늘 돌았다"
    else
        MISSING+=("$label")
        log "   $label: 오늘 돈 기록이 없다"
    fi
}

log "── 배치 확인"
check_ran evening_update.log "저녁 배치(19:40)"
check_ran backup_db.log      "DB 백업(06:00)"

if [ ${#MISSING[@]} -gt 0 ]; then
    notify "⚠️ 서버 배치가 돌지 않았습니다"$'\n\n'"$(printf '%s\n' "${MISSING[@]}")"$'\n'"cron 을 확인하세요: sudo -u stock crontab -l"
fi

# 데이터가 신선한지도 여기서 본다. 저녁 배치 안에서도 돌지만, 그 배치가
# 안 돌았으면 점검도 같이 안 돈다. 밖에서 한 번 더 본다.
if ! FRESH=$(ssh "$REMOTE" "$APP check_freshness --quiet --log-level error" 2>&1); then
    log "── 신선도 점검에서 걸렸다"
    printf '%s\n' "$FRESH" | sed 's/^/     /' | tee -a "$LOG"
    notify "⚠️ 데이터가 신선하지 않습니다"$'\n\n'"$(printf '%s' "$FRESH" | grep -v '^$' | head -8)"
fi


# ── 할 일 받아오기 ──
if ! PENDING=$(ssh "$REMOTE" "$RUN --list-pending" 2>>"$LOG"); then
    log "서버 접속 실패 — 끝낸다"
    # 서버가 안 되면 텔레그램도 서버를 거치므로 보낼 수 없다. 로그만 남긴다.
    exit 1
fi

if [ -z "$PENDING" ]; then
    log "받을 것 없음 (이미 판단이 있거나 데이터가 아직 없다)"
    exit 0
fi

COUNT=$(echo "$PENDING" | wc -l | tr -d ' ')
log "대상 ${COUNT}건"

OK=0
TOTAL_COST=0
FAILED=()
LINES=()

while read -r kind key basis; do
    [ -z "${key:-}" ] && continue
    log "── $key ($basis)"

    if ! ssh "$REMOTE" "$RUN --kind $kind --key $key --emit-prompt" \
            > "$WORK/p.txt" 2>>"$LOG"; then
        log "   프롬프트 받기 실패"
        FAILED+=("$key(프롬프트)")
        continue
    fi
    log "   프롬프트 $(wc -c < "$WORK/p.txt" | tr -d ' ') 바이트"

    # 빈 디렉터리에서 부른다. 프로젝트 안에서 부르면 CLAUDE.md 와 둘레
    # 파일을 맥락에 얹는다 — 날마다 쌓아 견주는 판단에 섞이면 안 된다.
    if ! (cd "$WORK" && "$CLAUDE" -p --output-format json \
            --allowedTools "$TOOLS" --model "$MODEL" < "$WORK/p.txt") \
            > "$WORK/raw.json" 2>>"$LOG"; then
        log "   claude 호출 실패"
        FAILED+=("$key(claude)")
        continue
    fi

    # is_error 와 result 를 꺼낸다. 인증이 풀렸는지도 여기서 가린다 —
    # 사람이 할 일이 다르다(기다리면 되는 것과, 다시 로그인해야 하는 것).
    # 비용은 stdout 으로 나온다. 잡지 않으면 로그에 날것으로 샌다.
    if ! COST=$(python3 - "$WORK/raw.json" "$WORK/a.txt" <<'PY' 2>>"$LOG"
import json, sys
raw, out = sys.argv[1], sys.argv[2]
d = json.load(open(raw))
if d.get('is_error') or d.get('subtype') != 'success':
    msg = str(d.get('result') or d.get('subtype'))
    low = msg.lower()
    kind = 'AUTH' if any(h in low for h in
        ('login', 'authenticat', 'unauthorized', 'oauth', 'expired')) else 'FAIL'
    print(f'{kind}: {msg[:200]}', file=sys.stderr)
    sys.exit(2 if kind == 'AUTH' else 1)
text = (d.get('result') or '').strip()
if not text:
    print('FAIL: 답변이 비어 있다', file=sys.stderr)
    sys.exit(1)
open(out, 'w').write(text)
print(f"{d.get('total_cost_usd', 0):.4f}")
PY
    )
    then
        rc=$?
        if [ "$rc" = 2 ]; then
            log "   Claude 로그인이 풀렸다"
            notify "⚠️ AI 시황 판단 멈춤"$'\n\n'"Claude 로그인이 풀렸습니다."$'\n'"맥에서: claude login"
            exit 1   # 하나가 인증이면 나머지도 다 막힌다. 한도만 깎지 않는다.
        fi
        log "   답변 처리 실패"
        FAILED+=("$key(응답)")
        continue
    fi

    log "   답변 $(wc -c < "$WORK/a.txt" | tr -d ' ') 바이트 | \$${COST}"
    TOTAL_COST=$(python3 -c "print(f'{${TOTAL_COST:-0} + ${COST:-0}:.4f}')")

    if ! RESULT=$(ssh "$REMOTE" "$RUN --kind $kind --key $key --basis $basis --save-answer" \
                  < "$WORK/a.txt" 2>&1); then
        log "   저장 실패: $RESULT"
        FAILED+=("$key(저장)")
        continue
    fi
    log "   $RESULT"
    OK=$((OK + 1))
    # 저장 로그에서 '| 스탠스 | 한 줄 결론' 부분만 뽑아 알림에 싣는다
    LINES+=("$key $(echo "$RESULT" | sed -n 's/.*\] [0-9-]* [^ |]* | //p' | cut -c1-70)")
done <<< "$PENDING"

# ── 알림 ──
# 배열을 IFS 로 잇지 않는다 — 첫 글자 하나로만 이어 붙어 ', ' 가 ',' 가 된다.
join_nl()    { printf '%s\n' "$@"; }
join_comma() { printf '%s, ' "$@" | sed 's/, $//'; }

if [ ${#FAILED[@]} -gt 0 ]; then
    body="⚠️ AI 시황 판단 | 성공 ${OK}건, 실패 ${#FAILED[@]}건"
    body+=$'\n\n'"실패: $(join_comma "${FAILED[@]}")"
    [ ${#LINES[@]} -gt 0 ] && body+=$'\n\n'"$(join_nl "${LINES[@]}")"
    notify "$body"
    log "완료 | 성공 $OK, 실패 ${#FAILED[@]} | \$${TOTAL_COST}"
    exit 1
fi

notify "🧠 AI 시황 판단 ${OK}건"$'\n\n'"$(join_nl "${LINES[@]}")"
log "완료 | 성공 $OK | \$${TOTAL_COST}"
