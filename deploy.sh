#!/bin/bash
#
# 배포 — git pull 부터 재시작까지.
#
#   /home/stock/jstocks/deploy.sh
#
# 왜 있나
#   앱은 stock 계정으로 돌고 파일도 전부 그 계정 것이다. root 로 git pull
#   하면 새로 받은 파일만 root 소유가 되어 앱이 못 읽거나 못 쓴다.
#   그래서 모든 명령에 sudo -u stock 이 붙는데, 하나라도 빠뜨리면 그날은
#   멀쩡해 보이고 다음 배치에서 터진다.
#
#   git 이 'dubious ownership' 으로 막아 주기는 한다. 다만 안내문이
#   safe.directory 를 추가하라고 하는데, 그대로 따르면 막아 주던 것까지
#   없어진다. 그 유혹을 없애려고 이 스크립트를 둔다.
#
# [주의] root 로 실행한다. 안에서 stock 으로 낮춰 돈다.

set -euo pipefail

APP=/home/stock/jstocks
USER=stock

if [ ! -d "$APP" ]; then
    echo "오류: $APP 가 없습니다. 서버에서만 실행하세요."
    exit 1
fi
if [ "$(id -u)" -ne 0 ]; then
    echo "오류: root 로 실행하세요 (안에서 $USER 로 낮춰 돕니다)."
    exit 1
fi

cd "$APP"
run() { echo "  \$ $*"; sudo -u "$USER" "$@"; }

echo "== 받기"
run git pull

echo "== 패키지"
# requirements.txt 가 바뀌었을 때만. 늘 돌리면 1~2분이 그냥 간다.
if ! sudo -u "$USER" git diff --quiet HEAD@{1} HEAD -- requirements.txt 2>/dev/null; then
    run venv/bin/pip install -q -r requirements.txt
else
    echo "  (바뀐 것 없음)"
fi

echo "== 마이그레이션"
# makemigrations 는 상용에서 돌리지 않는다. 로컬에서 만들어 커밋하고
# 여기서는 적용만 한다. 그러지 않으면 번호가 갈라진다.
run venv/bin/python manage.py migrate --noinput

echo "== 정적 파일"
run venv/bin/python manage.py collectstatic --noinput -v 0

echo "== 재시작"
systemctl restart jstocks
sleep 2
systemctl is-active --quiet jstocks && echo "  jstocks 떴습니다" || {
    echo "  !! jstocks 가 안 떴습니다"
    journalctl -u jstocks -n 20 --no-pager
    exit 1
}

echo "== 확인"
code=$(curl -s -o /dev/null -w '%{http_code}' https://cantoluna3.cafe24.com/login/ || echo 000)
echo "  https://cantoluna3.cafe24.com/login/ -> $code"
root_owned=$(find /home/stock -user root 2>/dev/null | head -5)
if [ -n "$root_owned" ]; then
    echo "  !! root 소유 파일이 생겼습니다:"
    printf '%s\n' "$root_owned" | sed 's/^/     /'
    echo "     chown -R stock:stock /home/stock 로 되돌리세요"
    exit 1
fi
echo "  root 소유 파일 없음"
