#!/bin/bash
#
# 일일 데이터 업데이트 스크립트
# 장 마감 후 실행 (평일 18:00)
#
# crontab 설정:
#   0 18 * * 1-5 /home/stock/jstocks/daily_update.sh >> /home/stock/jstocks/logs/daily_update.log 2>&1
#

cd /home/stock/jstocks
source venv/bin/activate

echo "========================================"
echo "일일 업데이트 시작: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

# 시황
echo "[1/13] 지수 차트..."
python manage.py save_index_chart --mode last --log-level info

echo "[2/13] 시장 동향..."
python manage.py save_market_trend --mode last --log-level info

# 업종
echo "[3/13] 업종..."
python manage.py save_sector --mode last --log-level info

# 종목 기본정보
echo "[4/13] 종목 기본정보..."
python manage.py save_stock_info --code all --log-level info

# 종목 차트
echo "[5/13] 일봉 차트..."
python manage.py save_daily_chart --code all --mode last --log-level info

echo "[6/13] 주봉 차트..."
python manage.py save_weekly_chart --code all --mode last --log-level info

echo "[7/13] 월봉 차트..."
python manage.py save_monthly_chart --code all --mode last --log-level info

# 종목 수급 (관심 종목만)
echo "[8/13] 투자자 매매동향..."
python manage.py save_investor_trend --code fav --mode last --log-level info

echo "[9/13] 공매도..."
python manage.py save_short_selling --code fav --mode last --log-level info

# 종목 뉴스 (관심 종목만)
echo "[10/13] 공시..."
python manage.py save_gongsi_stock --code fav --log-level info

echo "[11/13] 리포트..."
python manage.py save_fnguide_report --code fav --log-level info

echo "[12/13] 노다지..."
python manage.py save_nodaji_stock --code fav --log-level info

# ETF 차트
echo "[13/13] ETF 차트..."
python manage.py save_etf_chart --mode last --log-level info

echo "========================================"
echo "일일 업데이트 완료: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"
