# -*- coding: utf-8 -*-
"""
기업분석 프롬프트에 사업보고서 본문을 자동으로 넣는다.

지금까지는 이랬다 — 프롬프트를 복사하고, DART 에서 사업보고서 PDF 를 내려받고,
claude.ai 에 첨부하고, 붙여넣었다. 종목마다 네 번의 손이 갔고 그래서 잘 안 했다.

DART 뷰어는 정기보고서를 목차 절 단위로 쪼개 놓는다. 절 하나만 골라 받으면
PDF 통째(4MB)가 아니라 필요한 40~60K자만 가져올 수 있다. 그걸 프롬프트의
{사업보고서} 자리에 채운다.

프롬프트 안에서 절을 지정한다:
    {사업보고서}                          II. 사업의 내용 (기본값)
    {사업보고서:이사회,주주에 관한 사항}     골라서

설정 화면도 마이그레이션도 필요 없다 — 프롬프트를 고치는 사람이 곧 절을 정한다.
{공시본문}·{수급요약}과 같은 방식이다.
"""
import re
from datetime import timedelta

# {사업보고서} 또는 {사업보고서:절이름,절이름}
VARIABLE_RE = re.compile(r'\{사업보고서(?::([^}]*))?\}')

# 절을 안 적으면 여기. 사업 내용·제품·매출·수주·연구개발활동이 다 들어 있어
# 기업분석 프롬프트 대부분이 이 한 절이면 된다.
DEFAULT_SECTIONS = ['사업의 내용']

# 정기보고서 최상위 목차는 사업·반기·분기보고서가 모두 같다.
#   I. 회사의 개요            II. 사업의 내용
#   III. 재무에 관한 사항      IV. 이사의 경영진단 및 분석의견
#   V. 회계감사인의 감사의견 등  VI. 이사회 등 회사의 기관에 관한 사항
#   VII. 주주에 관한 사항      VIII. 임원 및 직원 등에 관한 사항
#   IX. 계열회사 등에 관한 사항 X. 대주주 등과의 거래내용
#   XI. 그 밖에 …             XII. 상세표
#
# 넣지 않는 절이 둘 있다.
#   III. 재무에 관한 사항   약 2.5MB. 재무제표는 이미 DB 에 있다.
#   VIII. 임원 및 직원      삼성전자 134,373자. 대부분 개인별 보수 표다.

# 정기보고서를 찾을 창. 분기보고서가 1년에 네 번 나오므로 넉넉히 잡아도
# 최신 한 건만 쓴다. 상장 직후라 아직 없는 종목은 그렇다고 알려준다.
LOOKBACK_DAYS = 500

# 절을 다 합친 글자 수 상한. II. 사업의 내용이 40~65K, 지배구조 셋이 54~57K다.
# 여유를 두되 실수로 III(2.5MB)이 지정됐을 때 멈추게 한다.
MAX_CHARS = 200_000

REGULAR_RE = r'(사업보고서|반기보고서|분기보고서)'

_SPACE_RE = re.compile(r'\s+')


def _norm(text):
    """'사 업 보 고 서' 처럼 DART 는 글자 사이를 벌려 놓는다. 붙여서 견준다."""
    return _SPACE_RE.sub('', text or '')


def parse_spec(prompt):
    """
    프롬프트에서 {사업보고서} 를 찾아 절 목록을 준다.

    없으면 None — 사업보고서를 안 쓰는 프롬프트라는 뜻이다.
    """
    match = VARIABLE_RE.search(prompt or '')
    if not match:
        return None
    raw = (match.group(1) or '').strip()
    if not raw:
        return list(DEFAULT_SECTIONS)
    return [s.strip() for s in raw.split(',') if s.strip()]


def latest_regular_report(stock):
    """가장 최근 정기보고서 공시. 접수번호가 있는 것만."""
    from django.utils import timezone

    from .models import Gongsi

    cut = timezone.localdate() - timedelta(days=LOOKBACK_DAYS)
    rows = (Gongsi.objects
            .filter(stock=stock, date__gte=cut, title__regex=REGULAR_RE)
            .order_by('-date'))
    for row in rows:
        if 'rcpNo=' in (row.link or ''):
            return row
    return None


def pick_nodes(nodes, sections):
    """
    목차 노드 중 지정한 절만. 지정한 순서가 아니라 목차 순서로 준다 —
    보고서에 실린 차례가 곧 읽는 차례다.
    """
    wanted = [_norm(s) for s in sections]
    picked, matched = [], set()
    for node in nodes:
        text = _norm(node.get('text'))
        for i, key in enumerate(wanted):
            if key and key in text:
                picked.append(node)
                matched.add(i)
                break
    missing = [sections[i] for i in range(len(sections)) if i not in matched]
    return picked, missing
