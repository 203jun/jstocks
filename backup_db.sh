#!/bin/bash
#
# DB 백업 — 날마다 한 번 (주말 포함)
#
# crontab 설정:
#   0 6 * * * /home/stock/jstocks/backup_db.sh >> /home/stock/jstocks/logs/backup_db.log 2>&1
#
# 왜 아침 6시인가
#   배치가 15:40 · 19:40 에 돈다. 그 전에 떠 두면 배치가 무언가를 망쳤을 때
#   돌아갈 자리가 생긴다. 새벽이라 다른 일과도 겹치지 않는다.
#
# 왜 주말에도 도나
#   시세는 안 바뀌지만 메모·AI 판단·리서치는 주말에도 쓴다. 그것들이
#   되찾을 수 없는 것이다 — 시세는 다시 받으면 된다.
#
# [주의] 로컬에서 실행 금지! 서버(/home/stock/jstocks)에서만 실행하세요.
#

if [ ! -d "/home/stock/jstocks" ]; then
    echo "오류: 이 스크립트는 서버에서만 실행할 수 있습니다."
    exit 1
fi

cd /home/stock/jstocks
source venv/bin/activate
source ./batch_lib.sh

batch_start "DB 백업" 1

step "DB 백업" python manage.py backup_db --log-level info

batch_finish "DB 백업"
