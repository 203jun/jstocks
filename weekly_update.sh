#!/bin/bash
#
# 주간 데이터 업데이트 스크립트
# 주말에 실행 (토요일 10:00)
#
# [주의] 로컬에서 실행 금지! 서버(/home/stock/jstocks)에서만 실행하세요.
#
# crontab 설정:
#   0 10 * * 6 /home/stock/jstocks/weekly_update.sh >> /home/stock/jstocks/logs/weekly_update.log 2>&1
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
echo "주간 업데이트 시작: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

# 재무제표 (네이버)
echo "[1/1] 재무제표..."
python manage.py save_financial_naver --code all --log-level info

echo "========================================"
echo "주간 업데이트 완료: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"
