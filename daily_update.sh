#!/bin/bash
#
# 일일 데이터 업데이트 스크립트
# 장 마감 후 실행 (평일 15:40)
#
# [주의] 로컬에서 실행 금지! 서버(/home/stock/jstocks)에서만 실행하세요.
#
# crontab 설정:
#   40 15 * * 1-5 /home/stock/jstocks/daily_update.sh >> /home/stock/jstocks/logs/daily_update.log 2>&1
#
# 실패를 알리는 방식
#   예전에는 무엇이 터져도 마지막에 '✅ 완료' 한 줄만 보냈다. 공시 수집이 두 달
#   동안 한 건도 못 받고 있었는데 그 사이에도 매일 완료가 왔다.
#   이제 단계마다 종료코드와 '오류: N개' 요약을 보고, 걸린 것이 있으면 이름과
#   마지막 줄들을 텔레그램에 같이 실어 보낸다.
#

# 서버 경로 체크
if [ ! -d "/home/stock/jstocks" ]; then
    echo "오류: 이 스크립트는 서버에서만 실행할 수 있습니다."
    echo "경로 /home/stock/jstocks 가 존재하지 않습니다."
    exit 1
fi

cd /home/stock/jstocks
source venv/bin/activate

# 텔레그램 알림 함수
send_telegram() {
    python manage.py tele_api_test -m "$1" > /dev/null 2>&1
}

TOTAL_STEPS=18
STEP_NO=0
FAIL_NAMES=()
WARN_NAMES=()
DETAIL=""

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

    # 명령들이 끝에 '완료 | 성공: N개, ... 오류: K개' 를 찍는다 (열다섯 곳의 공통 관례).
    # 0개가 아닌 것만 집는다.
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

# 시작 알림
send_telegram "📊 일일 업데이트 시작 ($(date '+%H:%M'))"

echo "========================================"
echo "일일 업데이트 시작: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

# 토큰 발급 (키움 API 사용 전 필수)
step "토큰 발급" python manage.py get_token

# 휴장일 체크 (휴장이면 스크립트 종료)
# step 으로 감싸지 않는다 — 종료코드로 '오늘은 쉬는 날' 을 말하는 자리다.
STEP_NO=$((STEP_NO + 1))
echo "[${STEP_NO}/${TOTAL_STEPS}] 휴장일 체크..."
python manage.py check_market_open || exit 0

# 시황
step "지수 차트"   python manage.py save_index_chart --mode last --log-level info
step "시장 동향"   python manage.py save_market_trend --mode last --log-level info
# 시장 지표 (지수 차트 + 시장 동향 이후 실행)
step "시장 지표"   python manage.py save_market_indicator --mode last --log-level info

# 종목 기본정보
step "종목 기본정보" python manage.py save_stock_info --code all --log-level info

# 종목 차트
step "일봉 차트"   python manage.py save_daily_chart --code all --mode last --log-level info
step "주봉 차트"   python manage.py save_weekly_chart --code all --mode last --log-level info
step "월봉 차트"   python manage.py save_monthly_chart --code all --mode last --log-level info

# 업종 (일봉 차트 이후 실행)
step "업종"        python manage.py save_sector --mode last --log-level info

# 종목 수급 (관심 종목만)
step "투자자 매매동향" python manage.py save_investor_trend --code fav --mode last --log-level info
step "공매도"      python manage.py save_short_selling --code fav --mode last --log-level info

# 종목 뉴스 (관심 종목만)
step "공시"        python manage.py save_gongsi_stock --code fav --log-level info
step "리포트"      python manage.py save_fnguide_report --code fav --log-level info

# ETF
step "ETF 차트"    python manage.py save_etf_chart --mode last --log-level info
step "ETF 정보"    python manage.py save_etf_info --log-level info

# 계좌
step "계좌 자산 스냅샷" python manage.py save_daily_account --log-level info
step "매매일지"    python manage.py save_daily_diary --log-level info

echo "========================================"
echo "일일 업데이트 완료: $(date '+%Y-%m-%d %H:%M:%S')"
if [ ${#FAIL_NAMES[@]} -gt 0 ]; then
    echo "실패: ${FAIL_NAMES[*]}"
fi
if [ ${#WARN_NAMES[@]} -gt 0 ]; then
    echo "오류 섞임: ${WARN_NAMES[*]}"
fi
echo "========================================"

# 완료 알림 — 걸린 것이 있으면 이름과 원인을 같이 보낸다
if [ ${#FAIL_NAMES[@]} -eq 0 ] && [ ${#WARN_NAMES[@]} -eq 0 ]; then
    send_telegram "✅ 일일 업데이트 완료 ($(date '+%H:%M'))"
else
    MSG="⚠️ 일일 업데이트 완료 ($(date '+%H:%M'))"
    if [ ${#FAIL_NAMES[@]} -gt 0 ]; then
        MSG+=$'\n'"실패 ${#FAIL_NAMES[@]}: $(printf '%s, ' "${FAIL_NAMES[@]}" | sed 's/, $//')"
    fi
    if [ ${#WARN_NAMES[@]} -gt 0 ]; then
        MSG+=$'\n'"오류 섞임 ${#WARN_NAMES[@]}: $(printf '%s, ' "${WARN_NAMES[@]}" | sed 's/, $//')"
    fi
    # 줄 수로 자른다. 텔레그램은 4096자까지지만 길면 읽히지 않는다.
    MSG+=$'\n'"$(echo "$DETAIL" | head -16)"
    send_telegram "$MSG"
fi
