#!/bin/bash
#
# 다음 금융 수급 데이터 업데이트 스크립트
# 평일 19:40 실행
#
# [주의] 로컬에서 실행 금지! 서버(/home/stock/jstocks)에서만 실행하세요.
#
# crontab 설정:
#   40 19 * * 1-5 /home/stock/jstocks/daum_update.sh >> /home/stock/jstocks/logs/daum_update.log 2>&1
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

echo "========================================"
echo "다음 금융 수급 업데이트 시작: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

# 관심종목 수급 데이터 (다음 금융)
echo "[1/1] 수급 데이터 (다음 금융)..."
python manage.py save_investor_daum --code fav --mode last --log-level info

echo "========================================"
echo "다음 금융 수급 업데이트 완료: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

# 완료 알림
send_telegram "✅ 다음 금융 수급 업데이트 완료 ($(date '+%H:%M'))"
