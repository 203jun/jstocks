#!/bin/bash
#
# 일일 데이터 업데이트 스크립트
# 장 마감 후 실행 (평일 18:00)
#
# [주의] 로컬에서 실행 금지! 서버(/home/stock/jstocks)에서만 실행하세요.
#
# crontab 설정:
#   0 18 * * 1-5 /home/stock/jstocks/daily_update.sh >> /home/stock/jstocks/logs/daily_update.log 2>&1
#

# 서버 경로 체크
if [ ! -d "/home/stock/jstocks" ]; then
    echo "오류: 이 스크립트는 서버에서만 실행할 수 있습니다."
    echo "경로 /home/stock/jstocks 가 존재하지 않습니다."
    exit 1
fi

cd /home/stock/jstocks
source venv/bin/activate

echo "========================================"
echo "일일 업데이트 시작: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

# 토큰 발급 (키움 API 사용 전 필수)
echo "[1/15] 토큰 발급..."
python manage.py get_token

# 휴장일 체크 (휴장이면 스크립트 종료)
echo "[2/15] 휴장일 체크..."
python manage.py check_market_open || exit 0

# 시황
echo "[3/15] 지수 차트..."
python manage.py save_index_chart --mode last --log-level info

echo "[4/15] 시장 동향..."
python manage.py save_market_trend --mode last --log-level info

# 종목 기본정보
echo "[5/15] 종목 기본정보..."
python manage.py save_stock_info --code all --log-level info

# 종목 차트
echo "[6/15] 일봉 차트..."
python manage.py save_daily_chart --code all --mode last --log-level info

echo "[7/15] 주봉 차트..."
python manage.py save_weekly_chart --code all --mode last --log-level info

echo "[8/15] 월봉 차트..."
python manage.py save_monthly_chart --code all --mode last --log-level info

# 업종 (일봉 차트 이후 실행)
echo "[9/15] 업종..."
python manage.py save_sector --mode last --log-level info

# 종목 수급 (관심 종목만)
echo "[10/15] 투자자 매매동향..."
python manage.py save_investor_trend --code fav --mode last --log-level info

echo "[11/15] 공매도..."
python manage.py save_short_selling --code fav --mode last --log-level info

# 종목 뉴스 (관심 종목만)
echo "[12/15] 공시..."
python manage.py save_gongsi_stock --code fav --log-level info

echo "[13/15] 리포트..."
python manage.py save_fnguide_report --code fav --log-level info

echo "[14/15] 노다지..."
python manage.py save_nodaji_stock --code fav --log-level info

# ETF 차트
echo "[15/15] ETF 차트..."
python manage.py save_etf_chart --mode last --log-level info

echo "========================================"
echo "일일 업데이트 완료: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"
