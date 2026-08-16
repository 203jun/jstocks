# -*- coding: utf-8 -*-
"""
AI 답변에서 한 줄 결론과 매매 스탠스를 뽑아낸다.

프롬프트가 출력 형식을 정해두긴 했지만 AI 는 형식을 어길 수 있다.
그래서 여기서는 실패해도 되게 만든다 — 못 뽑으면 빈 값을 주고,
화면에서 사람이 채우면 된다. 억지로 추측해 엉뚱한 값을 넣지 않는다.

기대하는 형식:

    **한 줄 결론**: 약세 레짐 한복판에서 나온 단기 과열 반등 — …

    **매매 스탠스**

    **관망.** 지금은 종목을 새로 사도 되는 환경이 아니야. …
"""
import re

STANCES = ['공격적', '보통', '신중', '관망']

HEADLINE_MAX = 300

# 판단 이후 지표가 이만큼(거래일) 쌓이면 '다시 물어볼 때'로 본다.
# 일주일. 달력 날짜가 아니라 거래일이라 주말·연휴에 괜히 늘지 않는다.
STALE_TRADING_DAYS = 5

# "**한 줄 결론**:" / "## 한 줄 결론" / "한 줄 결론 -" 등 앞뒤 장식을 흘려보낸다
_HEADLINE_RE = re.compile(r'한\s*줄\s*결론[^\n:：\-]*[:：\-]?\s*(.*)', re.S)
_STANCE_SECTION_RE = re.compile(r'매매\s*스탠스[^\n:：\-]*[:：\-]?\s*(.*)', re.S)
_STANCE_RE = re.compile('|'.join(STANCES))

# 굵게/제목 표시 등 값이 아닌 글자
_DECOR = '*_#`> '


def _clean(text):
    return text.strip().strip(_DECOR).strip()


def _first_meaningful_line(text):
    """빈 줄과 장식만 있는 줄을 건너뛰고 첫 내용 줄을 준다"""
    for line in text.split('\n'):
        line = _clean(line)
        if line:
            return line
    return ''


def extract_headline(content):
    """
    한 줄 결론. 제목 줄과 본문이 떨어져 있는 경우(제목 다음 줄에 내용)도 잡는다.
    못 찾으면 답변의 첫 내용 줄을 쓴다 — 비워두는 것보다는 낫다.
    """
    match = _HEADLINE_RE.search(content)
    text = _first_meaningful_line(match.group(1)) if match else ''
    if not text:
        text = _first_meaningful_line(content)
    return text[:HEADLINE_MAX]


def extract_stance(content):
    """
    매매 스탠스. '매매 스탠스' 절 안에서 먼저 찾고, 없으면 빈 값.

    전체 본문에서 찾으면 안 된다 — 프롬프트 설명이나 다른 문장에 섞인
    "관망"이 잡혀 엉뚱한 스탠스가 저장된다.
    """
    match = _STANCE_SECTION_RE.search(content)
    if not match:
        return ''
    found = _STANCE_RE.search(match.group(1))
    return found.group(0) if found else ''


def parse(content):
    """붙여넣은 답변 -> {headline, stance}"""
    return {
        'headline': extract_headline(content),
        'stance': extract_stance(content),
    }


def build_analysis_panel(market, limit=12):
    """
    화면에 뿌릴 최신 판단 + 이력.

    '낡음'은 달력 날짜가 아니라 그 뒤로 쌓인 거래일 수로 본다.
    그날 물어봤으면 0 이고, 주말·연휴에는 늘어나지 않는다.
    """
    from .models import MarketAnalysis, MarketIndicator

    rows = list(
        MarketAnalysis.objects.filter(market=market)
        .order_by('-date')
        .values('date', 'headline', 'stance')[:limit]
    )
    if not rows:
        return None

    latest = MarketAnalysis.objects.filter(market=market).order_by('-date').first()
    behind = MarketIndicator.objects.filter(market=market, date__gt=latest.date).count()
    return {
        'latest': latest,
        'behind': behind,          # 판단 이후 쌓인 거래일 수
        'stale': behind >= STALE_TRADING_DAYS,
        'history': rows,
    }
