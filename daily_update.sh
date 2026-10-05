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
# 실패를 알리는 장치는 batch_lib.sh 에 있다 (주간 배치와 같이 쓴다).
#

# 서버 경로 체크
if [ ! -d "/home/stock/jstocks" ]; then
    echo "오류: 이 스크립트는 서버에서만 실행할 수 있습니다."
    echo "경로 /home/stock/jstocks 가 존재하지 않습니다."
    exit 1
fi

cd /home/stock/jstocks
source venv/bin/activate
source ./batch_lib.sh

batch_start "일일" 18 "📊"

# 토큰 발급 (키움 API 사용 전 필수)
step "토큰 발급" python manage.py get_token

# 휴장일 체크 (휴장이면 스크립트 종료)
# step 으로 감싸지 않는다 — 여기서 종료코드는 '오늘은 쉬는 날' 을 뜻한다.
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

batch_finish "일일"
