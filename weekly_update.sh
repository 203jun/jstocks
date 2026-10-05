#!/bin/bash
#
# 주간 데이터 업데이트 스크립트
# 주말 직전에 실행 (금요일 23:00)
#
# [주의] 로컬에서 실행 금지! 서버(/home/stock/jstocks)에서만 실행하세요.
#
# crontab 설정:
#   0 23 * * 5 /home/stock/jstocks/weekly_update.sh >> /home/stock/jstocks/logs/weekly_update.log 2>&1
#
# 실패를 알리는 장치는 batch_lib.sh 에 있다 (일일 배치와 같이 쓴다).
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

batch_start "주간" 2

# 재무제표 (네이버)
step "재무제표" python manage.py save_financial_naver --code all --log-level info

# 컨센서스 (분기 실적이라 자주 안 바뀐다. 관심 종목만)
step "컨센서스" python manage.py save_consensus --code fav --log-level info

batch_finish "주간"
