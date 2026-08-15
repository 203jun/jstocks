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

# 시작 알림
send_telegram "📊 일일 업데이트 시작 ($(date '+%H:%M'))"

echo "========================================"
echo "일일 업데이트 시작: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

# 토큰 발급 (키움 API 사용 전 필수)
echo "[1/19] 토큰 발급..."
python manage.py get_token

# 휴장일 체크 (휴장이면 스크립트 종료)
echo "[2/19] 휴장일 체크..."
python manage.py check_market_open || exit 0

# 시황
echo "[3/19] 지수 차트..."
python manage.py save_index_chart --mode last --log-level info

echo "[4/19] 시장 동향..."
python manage.py save_market_trend --mode last --log-level info

# 시장 지표 (지수 차트 + 시장 동향 이후 실행)
echo "[5/19] 시장 지표..."
python manage.py save_market_indicator --mode last --log-level info

# 종목 기본정보
echo "[6/19] 종목 기본정보..."
python manage.py save_stock_info --code all --log-level info

# 종목 차트
echo "[7/19] 일봉 차트..."
python manage.py save_daily_chart --code all --mode last --log-level info

echo "[8/19] 주봉 차트..."
python manage.py save_weekly_chart --code all --mode last --log-level info

echo "[9/19] 월봉 차트..."
python manage.py save_monthly_chart --code all --mode last --log-level info

# 업종 (일봉 차트 이후 실행)
echo "[10/19] 업종..."
python manage.py save_sector --mode last --log-level info

# 종목 수급 (관심 종목만)
echo "[11/19] 투자자 매매동향..."
python manage.py save_investor_trend --code fav --mode last --log-level info

echo "[12/19] 공매도..."
python manage.py save_short_selling --code fav --mode last --log-level info

# 종목 뉴스 (관심 종목만)
echo "[13/19] 공시..."
python manage.py save_gongsi_stock --code fav --log-level info

echo "[14/19] 리포트..."
python manage.py save_fnguide_report --code fav --log-level info

echo "[15/19] 노다지..."
python manage.py save_nodaji_stock --code fav --log-level info

# ETF
echo "[16/19] ETF 차트..."
python manage.py save_etf_chart --mode last --log-level info

echo "[17/19] ETF 정보..."
python manage.py save_etf_info --log-level info

# 계좌
echo "[18/19] 계좌 자산 스냅샷..."
python manage.py save_daily_account --log-level info

echo "[19/19] 매매일지..."
python manage.py save_daily_diary --log-level info

echo "========================================"
echo "일일 업데이트 완료: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

# 완료 알림
send_telegram "✅ 일일 업데이트 완료 ($(date '+%H:%M'))"
