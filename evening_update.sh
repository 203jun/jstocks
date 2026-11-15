#!/bin/bash
#
# 저녁 수급 업데이트 스크립트
# 평일 19:40 실행
#
# 수급은 장이 끝나고 한참 뒤에야 공개된다. 일일 배치(15:40)에서 받으면
# 전날 값이 오므로 수급만 따로 저녁에 받는다.
#
# 종목 수급(다음)은 키움과 같은 InvestorTrend 행의 다른 칸을 채우므로
# 15:40 에 들어간 값을 덮어쓰지 않는다 — 키움은 foreign/institution,
# 다음은 daum_foreign/daum_institution.
#
# 예전 이름은 daum_update.sh 였다. 다음 말고 네이버도 받게 되어 바꿨다.
#
# [주의] 로컬에서 실행 금지! 서버(/home/stock/jstocks)에서만 실행하세요.
#
# crontab 설정:
#   40 19 * * 1-5 /home/stock/jstocks/evening_update.sh >> /home/stock/jstocks/logs/evening_update.log 2>&1
#
# 실패를 알리는 장치는 batch_lib.sh 에 있다 (일일·주간 배치와 같이 쓴다).
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

batch_start "저녁 수급" 4

# 시장 수급 (네이버) — 코스피·코스닥 개인/외국인/기관
step "시장 동향"   python manage.py save_market_trend --mode last --log-level info

# 시장 지표 (시장 동향 이후 실행. 지수 차트는 15:40 에 이미 들어와 있다)
step "시장 지표"   python manage.py save_market_indicator --mode last --log-level info

# 종목 수급 (다음 금융, 관심 종목만)
step "수급 데이터 (다음 금융)" python manage.py save_investor_daum --code fav --mode last --log-level info

# 신선도 점검 — 맨 끝에 둔다. 그날 데이터가 다 들어온 뒤라야 뜻이 있다.
#
# 명령이 실패하면 종료코드로 알지만, 그것으로 못 잡는 고장이 있다. 명령은
# 성공했는데 입력이 썩은 경우다 — 수급이 석 달 끊긴 동안 시장 지표는
# 엉터리 값을 만들며 날마다 '완료' 를 찍었다.
step "신선도 점검" python manage.py check_freshness --quiet --log-level info

batch_finish "저녁 수급"
