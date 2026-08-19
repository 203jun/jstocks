# -*- coding: utf-8 -*-
"""
공시 제목을 보고 호재·악재·검토로 가른다.

제목 문자열에 키워드가 들어있는지만 본다. 본문을 읽지 않으므로 확실한 것만
가르고 나머지는 비워둔다 — 애매한 것에 배지를 붙이면 배지가 아무 말도 안
하게 된다. 실제로 화면의 여섯 줄 중 한 줄에만 붙는다.

키워드는 DART 실제 공시명과 맞아야 한다. 어긋나면 조용히 0건이 되고 화면에는
'아무것도 아닌 공시'로 보인다. '자기주식소각'으로 적어두었다가 8건을 놓친 적이
있다 — DART 는 '주식소각결정'으로 쓴다.

이 규칙을 프롬프트의 {읽는법}도 같이 읽는다. 화면과 프롬프트가 다른 기준으로
말하지 않게 하기 위해서다.
"""
import re
import unicodedata


def normalize(text):
    if not text:
        return ''
    text = unicodedata.normalize('NFC', text)
    for dot in ['ㆍ', '\u00b7', '\u2219', '\u2022', '\u0387', '\u30fb']:
        text = text.replace(dot, '')
    text = text.replace('\uff08', '(').replace('\uff09', ')')
    text = re.sub(r'\s+', '', text)
    for dash in ['\u2212', '\u2013', '\u2014', '\u30fc', '\u2500']:
        text = text.replace(dash, '-')
    return text


# 실제 공시명과 맞는지 데이터로 대조해 가며 고친다. 이름이 어긋나면 조용히
# 0건이 되고, 화면에는 '아무것도 아닌 공시'로 보인다 — 실제로 '자기주식소각'이
# 그랬다. DART 는 '주식소각결정'으로 쓴다.
#
# '결정'·'결과보고서' 같은 꼬리는 떼고 앞머리만 남긴다. 자기주식취득은
# 결정과 결과보고서가 따로 오는데 둘 다 같은 뜻이다.
POSITIVE = [
    '주식소각',              # 주식소각결정 — 유통 물량이 줄어든다
    '기업가치제고계획',
    '자기주식취득',          # 취득결정 · 취득결과보고서
    '주식배당결정',
    '무상증자결정',
    '특허권취득',
    '현금현물배당결정',
]
NEGATIVE = [
    '회생절차',
    '법정관리',
    '거래정지',
    '관리종목지정',
    '상장폐지',
    '감사의견거절',
    '감사의견한정',
    '부도',
    '횡령',
    '배임',
    '무상감자',
    '공급계약해지',
    '자기주식처분',          # 처분결정 · 처분결과보고서 — 물량이 시장에 나온다
    '유상증자결정',
    '전환사채권발행',
    '신주인수권부사채권발행',
    '교환사채권발행',
    '소송등의제기',
    '영업정지',
    '시정명령',
    '불성실공시',
]
# 지분 신고서는 넣지 않는다. 임원·주요주주 620건, 대량보유 181건으로
# '검토' 배지의 74%를 차지했다. 임원이 몇 주 샀다는 신고가 매번 배지를 달면
# 배지가 아무 말도 안 하게 된다. 지분 변동은 수급 탭에서 따로 본다.
REVIEW = [
    '영업(잠정)실적',
    '매출액또는손익구조',
    '타법인주식및출자증권취득',
    '타법인주식및출자증권처분',
    '유형자산취득',
    '유형자산처분',
    '영업양수',
    '영업양도',
    '회사합병결정',
    '회사분할결정',
    '단일판매공급계약체결',
    '특별관계자',
    '최대주주변경',
    '공개매수',
]


def classify(title):
    normalized = normalize(title)
    if not normalized:
        return None
    if '자기주식취득' in normalized and '신탁계약' in normalized:
        return '검토'
    for kw in NEGATIVE:
        if normalize(kw) in normalized:
            return '악재'
    for kw in POSITIVE:
        if normalize(kw) in normalized:
            return '호재'
    for kw in REVIEW:
        if normalize(kw) in normalized:
            return '검토'
    return None
