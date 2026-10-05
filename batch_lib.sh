#!/bin/bash
#
# 배치 스크립트 공용 조각 — daily_update.sh 와 weekly_update.sh 가 같이 쓴다.
#
# 쓰는 법
#
#   cd /home/stock/jstocks
#   source venv/bin/activate
#   source ./batch_lib.sh
#
#   batch_start "일일" 18
#   step "토큰 발급" python manage.py get_token
#   ...
#   batch_finish "일일"
#
# 왜 있나
#   예전에는 무엇이 터져도 마지막에 '✅ 완료' 한 줄만 보냈다. 공시 수집이 두 달
#   동안 한 건도 못 받는 중에도 매일 완료가 왔다. 알림이 늘 같은 말을 하면
#   알림이 아니다.
#
#   그 장치를 두 스크립트에 각각 두면 한쪽만 고쳐져 어긋난다. 여기 한 곳에 둔다.
#

# 텔레그램 알림
send_telegram() {
    python manage.py tele_api_test -m "$1" > /dev/null 2>&1
}

# batch_start "라벨" 전체단계수
batch_start() {
    BATCH_LABEL="$1"
    TOTAL_STEPS="$2"
    STEP_NO=0
    FAIL_NAMES=()
    WARN_NAMES=()
    DETAIL=""

    local icon="📊"
    [ "$BATCH_LABEL" = "주간" ] && icon="📈"
    send_telegram "${icon} ${BATCH_LABEL} 업데이트 시작 ($(date '+%H:%M'))"

    echo "========================================"
    echo "${BATCH_LABEL} 업데이트 시작: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "========================================"
}

# step "이름" <명령...>
#
# 한 단계를 돌리고 결과를 모은다. 한 단계가 실패해도 나머지는 계속 돈다 —
# 수급이 안 되는 날에 차트까지 멈출 이유가 없다.
step() {
    local name="$1"; shift
    STEP_NO=$((STEP_NO + 1))
    echo "[${STEP_NO}/${TOTAL_STEPS}] ${name}..."

    local tmp
    tmp=$(mktemp)
    "$@" 2>&1 | tee "$tmp"
    local rc=${PIPESTATUS[0]}

    # 명령들이 끝에 '완료 | 성공: N개, ... 오류: K개' 를 찍는다 (열다섯 곳의
    # 공통 관례). 0개가 아닌 것만 집는다.
    local errs
    errs=$(grep -oE '오류: [0-9]+개' "$tmp" | grep -v '오류: 0개' | tail -1)

    if [ "$rc" -ne 0 ]; then
        FAIL_NAMES+=("$name")
        # 마지막 줄들이 대개 원인을 말한다. 로그 전체를 보내면 읽히지 않는다.
        DETAIL+=$'\n'"· ${name} (종료코드 ${rc})"
        DETAIL+=$'\n'"$(grep -v '^[[:space:]]*$' "$tmp" | tail -3 | sed 's/^/  /')"
    elif [ -n "$errs" ]; then
        WARN_NAMES+=("$name")
        DETAIL+=$'\n'"· ${name} — ${errs}"
    fi

    rm -f "$tmp"
}

# 이름 목록을 ", " 로 잇는다.
# ${arr[*]} 와 IFS 로는 안 된다 — IFS 의 첫 글자만 구분자로 쓰여 공백이 빠진다.
_join_names() {
    printf '%s, ' "$@" | sed 's/, $//'
}

# batch_finish "라벨"
batch_finish() {
    local label="$1"

    echo "========================================"
    echo "${label} 업데이트 완료: $(date '+%Y-%m-%d %H:%M:%S')"
    [ ${#FAIL_NAMES[@]} -gt 0 ] && echo "실패: $(_join_names "${FAIL_NAMES[@]}")"
    [ ${#WARN_NAMES[@]} -gt 0 ] && echo "오류 섞임: $(_join_names "${WARN_NAMES[@]}")"
    echo "========================================"

    if [ ${#FAIL_NAMES[@]} -eq 0 ] && [ ${#WARN_NAMES[@]} -eq 0 ]; then
        send_telegram "✅ ${label} 업데이트 완료 ($(date '+%H:%M'))"
        return
    fi

    local msg="⚠️ ${label} 업데이트 완료 ($(date '+%H:%M'))"
    if [ ${#FAIL_NAMES[@]} -gt 0 ]; then
        msg+=$'\n'"실패 ${#FAIL_NAMES[@]}: $(_join_names "${FAIL_NAMES[@]}")"
    fi
    if [ ${#WARN_NAMES[@]} -gt 0 ]; then
        msg+=$'\n'"오류 섞임 ${#WARN_NAMES[@]}: $(_join_names "${WARN_NAMES[@]}")"
    fi
    # 줄 수로 자른다. 텔레그램은 4096자까지지만 길면 읽히지 않는다.
    msg+=$'\n'"$(echo "$DETAIL" | head -16)"
    send_telegram "$msg"
}
