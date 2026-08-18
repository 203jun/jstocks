# -*- coding: utf-8 -*-
"""
AI 답변을 날짜별로 붙여넣어 두는 자리 — 시황·리포트·수급·공시가 같이 쓴다.

돌아가는 방식은 어디서나 같다. 그날 프롬프트를 돌리고 답변을 통째로
붙여넣으면 한 줄 결론과 스탠스를 뽑아 기준일과 함께 저장한다. 같은
기준일에 다시 넣으면 덮어쓴다. 기준일은 사람이 고르지 않는다 — 그날의
데이터가 정한다(시황은 지표 기준일, 종목은 일봉 기준일).

자리마다 다른 것은 둘뿐이다.
  기준일을 무엇으로 잡을지
  판단 뒤로 무엇이 얼마나 쌓였는지 (다시 물어볼 때인지)
그 둘을 KINDS 한 곳에 모아둔다.

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

from django.utils.html import escape
from django.utils.safestring import mark_safe

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
_DECOR = '*_#`>=~ '

# 문장 안에 섞인 마크다운 표시. 한 줄 결론은 그대로 화면에 뿌리므로 걷어낸다.
_INLINE_MARK_RE = re.compile(r'\*\*|==|__|~~|`')

# 본문 렌더용. 줄을 넘어가면 문단을 통째로 삼키므로 한 줄 안에서만 잡는다.
_BOLD_RE = re.compile(r'\*\*([^*\n]+?)\*\*')
_MARK_RE = re.compile(r'==([^=\n]+?)==')


def _clean(text):
    return _INLINE_MARK_RE.sub('', text.strip().strip(_DECOR)).strip()


def render_content(content):
    """
    붙여넣은 답변을 화면용 HTML 로. 굵게(**)와 강조(==)만 살린다.

    사용자가 붙여넣는 텍스트라 먼저 이스케이프한 뒤 태그를 넣는다.
    줄바꿈은 CSS(white-space: pre-line)가 살리므로 <br> 을 넣지 않는다.
    """
    html = escape(content or '')
    html = _BOLD_RE.sub(r'<strong>\1</strong>', html)
    html = _MARK_RE.sub(r'<mark>\1</mark>', html)
    return mark_safe(html)


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


# ── 자리마다 다른 것 ────────────────────────────────────────────────
#
# basis(key)  기준일을 정한다. 그날 AI 가 본 데이터의 날짜다.
# behind(key, date)  판단 뒤로 쌓인 것의 개수. 0 이면 최신이다.
# unit  그 개수를 뭐라고 부를지.
#
# 시황·수급은 거래일로 센다 — 달력 날짜로 세면 주말에 괜히 낡아 보인다.
# 리포트·공시는 건수로 센다. 새 리포트가 나왔는지가 다시 물어볼 이유다.

def _market_basis(key):
    from .models import MarketIndicator
    row = MarketIndicator.objects.filter(market=key).order_by('-date').first()
    return row.date if row else None


def _stock_basis(key):
    from .models import DailyChart
    row = DailyChart.objects.filter(stock_id=key).order_by('-date').first()
    return row.date if row else None


def _count_after(model_path, field, key, date):
    from django.apps import apps
    model = apps.get_model('stocks', model_path)
    return model.objects.filter(**{field: key, 'date__gt': date}).count()


KINDS = {
    'market': {
        'basis': _market_basis,
        'behind': lambda key, date: _count_after('MarketIndicator', 'market', key, date),
        'unit': '지표 {n}거래일 갱신됨',
        'threshold': STALE_TRADING_DAYS,
    },
    'supply': {
        'basis': _stock_basis,
        'behind': lambda key, date: _count_after('DailyChart', 'stock_id', key, date),
        'unit': '수급 {n}거래일 갱신됨',
        'threshold': STALE_TRADING_DAYS,
    },
    'report': {
        'basis': _stock_basis,
        'behind': lambda key, date: _count_after('Report', 'stock_id', key, date),
        'unit': '그 뒤 리포트 {n}건',
        'threshold': 1,
    },
    'gongsi': {
        'basis': _stock_basis,
        'behind': lambda key, date: _count_after('Gongsi', 'stock_id', key, date),
        'unit': '그 뒤 공시 {n}건',
        'threshold': 3,
    },
}


def basis_date(kind, key):
    """이 자리에서 '오늘 판단'이 붙을 기준일. 데이터가 없으면 None."""
    spec = KINDS.get(kind)
    return spec['basis'](key) if spec else None


# 칩으로 늘어놓을 날짜 개수. 과거 판단은 거의 다시 안 본다 — 어제·그제
# 뭐라고 했는지 견주는 정도다. 넘치면 끝에 '…' 로 몇 건 더 있는지 알린다.
HISTORY_LIMIT = 5


def build_note_panel(kind, key, limit=HISTORY_LIMIT):
    """
    화면에 뿌릴 판단들. 날짜별 전문을 다 담아 보낸다 —
    날짜를 고를 때마다 서버에 다시 묻지 않기 위해서다.
    """
    from .models import AiNote

    spec = KINDS.get(kind)
    if not spec:
        return None
    qs = AiNote.objects.filter(kind=kind, key=key).order_by('-date')
    rows = list(qs[:limit])
    if not rows:
        return None
    more = qs.count() - len(rows)

    entries = []
    for row in rows:
        behind = spec['behind'](key, row.date)
        entries.append({
            'date': row.date.strftime('%Y-%m-%d'),
            'label': row.date.strftime('%-m/%-d'),
            # 예전에 저장된 행이나 손으로 고친 값에 ** 나 == 가 남아 있을 수 있다
            'headline': _clean(row.headline),
            'stance': row.stance,
            'content': row.content,
            'content_html': str(render_content(row.content)),
            'behind': behind,
            'behind_text': spec['unit'].format(n=behind) if behind else '',
            'stale': behind >= spec['threshold'],
        })
    return {'entries': entries, 'latest': entries[0], 'more': more}
