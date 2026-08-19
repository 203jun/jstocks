# -*- coding: utf-8 -*-
"""
공시 한 건을 놓고 "이게 매매 판단을 바꾸는가"를 묻는 프롬프트의 입력값.

공시 제목·본문·분류는 표의 행마다 다르므로 화면(JS)이 채운다. 여기서 만드는
것은 종목마다 한 번이면 되는 것들 — 주가가 어디쯤인지, 분류를 어떻게 읽어야
하는지다.

{주가맥락}이 있는 이유: 같은 공시라도 52주 고점에서 나온 것과 바닥에서 나온
것은 뜻이 다르다. 공시만 던져주면 그 자리를 알 수 없다.
"""
import re
from collections import Counter
from datetime import timedelta

from .gongsi_signal import NEGATIVE, POSITIVE, REVIEW, classify
from .supply_prompt import _price_context

# 훑는 창. 건수로 자르면 종목마다 기간이 제각각이다 — 공시가 잦은 곳은
# 두 달, 뜸한 곳은 1년 3개월치가 들어간다(관측 56~474일). 작년 공시를
# 오늘 판단에 넣을 이유가 없어 날짜로 자른다.
GONGSI_WINDOW_DAYS = 180

# 분류된 공시가 이보다 많으면 최근 것부터 자른다. 실제로 28건인 종목이 있다.
GONGSI_MAX_MARKED = 20

# 본문까지 넣어줄 공시 수와 한 건당 글자 수.
#
# DART 링크(dsaf001/main.do)는 프레임셋 껍데기라 AI 가 열어도 본문이 없다.
# 그래서 링크만 주지 않고 본문을 받아 넣는다. 다만 페이지를 그릴 때마다
# 받으면 느려지므로, 프롬프트 버튼을 누르는 순간 화면이 받아 채운다.
GONGSI_BODY_COUNT = 3
GONGSI_BODY_CHARS = 2500

# 프롬프트 편집 창의 변수 칩. 행마다 채워지는 것은 (행) 으로 표시한다.
GONGSI_VARIABLES = [
    ('{종목명}', ''),
    ('{종목코드}', ''),
    ('{오늘날짜}', ''),
    ('{현재가}', '현재가 · 등락률 · 거래량 전일비'),
    ('{공시제목}', '(행) 누른 공시의 제목'),
    ('{공시일자}', '(행)'),
    ('{공시분류}', '(행) 호재 / 악재 / 검토 / 없음'),
    ('{공시링크}', '(행) DART 원문 주소'),
    ('{공시내용}', '(행) DART 본문 — 여러 줄, 길면 거절된다'),
    ('{주가맥락}', '이동평균 대비 · 52주 고저 대비 — 여러 줄'),
    ('{읽는법}', '분류 규칙 (코드에서 자동 생성) — 여러 줄'),
]


GONGSI_ALL_VARIABLES = [
    ('{종목명}', ''),
    ('{종목코드}', ''),
    ('{기준일}', '데이터가 계산된 마지막 거래일'),
    ('{오늘날짜}', '오늘 날짜'),
    ('{현재가}', '현재가 · 등락률 · 거래량 전일비'),
    ('{공시목록}', '최근 180일 · 분류된 것은 한 줄씩, 나머지는 개수만 — 여러 줄'),
    ('{공시본문}', '눈여겨볼 공시 3건의 DART 본문 — 누를 때 받아온다, 여러 줄'),
    ('{주가맥락}', '이동평균 대비 · 52주 고저 대비 — 여러 줄'),
    ('{읽는법}', '분류 규칙 (코드에서 자동 생성) — 여러 줄'),
]


def _how_to_read():
    """
    분류 규칙을 그대로 풀어 쓴다. 화면의 배지와 같은 기준이라야
    "화면은 호재라는데 AI 는 아니라네" 같은 어긋남이 안 생긴다.
    """
    return '\n'.join([
        '공시 분류는 제목에 든 낱말만 보고 가른 것이다. 본문을 읽지 않았으므로 '
        '참고일 뿐이고, 최종 판단은 본문을 보고 하라.',
        '',
        '호재로 보는 제목: ' + ' · '.join(POSITIVE),
        '',
        '악재로 보는 제목: ' + ' · '.join(NEGATIVE),
        '',
        '검토로 보는 제목: ' + ' · '.join(REVIEW),
        '',
        '자기주식취득이라도 신탁계약을 통한 것은 검토로 둔다 — 직접 사들이는 '
        '것과 뜻이 다르다.',
        '',
        '분류가 "없음"인 공시가 대부분이다(전체의 85%). 임원 지분신고·주주총회 '
        '소집·기업설명회처럼 일상적인 신고가 많아서다. 분류가 없다고 해서 '
        '중요하지 않다는 뜻은 아니니 본문으로 판단하라.',
        '',
        '임원·주요주주 지분신고와 대량보유 신고는 일부러 분류에서 뺐다. 건수가 '
        '너무 많아 배지가 의미를 잃었다. 지분 변동은 수급 탭에서 지분율로 본다.',
    ])


def build_gongsi_prompt_vars(stock, charts_asc, today):
    """종목마다 한 번이면 되는 값들. 행별 값은 화면이 채운다."""
    price = f'{stock.current_price:,}원' if stock.current_price else '-'
    if stock.change_rate is not None:
        price += f' ({stock.change_rate:+}%)'
    if stock.volume_change is not None:
        price += f' · 거래량 전일비 {stock.volume_change:+}%'

    return {
        '{종목명}': stock.name,
        '{종목코드}': stock.code,
        '{오늘날짜}': f'{today:%Y-%m-%d}',
        '{현재가}': price,
        '{주가맥락}': _price_context(charts_asc, stock),
        '{읽는법}': _how_to_read(),
    }


def _gongsi_list(rows, today):
    """
    분류된 공시는 한 줄씩, 나머지는 유형과 개수로 접는다.

    나머지를 아주 빼지 않는 이유: 목록이 비면 '데이터가 없나' 로 헷갈린다.
    "49건 있었지만 다 일상 신고였다" 는 그 자체로 조용한 분기였다는 뜻이다.
    """
    cut = today - timedelta(days=GONGSI_WINDOW_DAYS)
    window = [g for g in rows if g.date >= cut]
    if not window:
        return f'최근 {GONGSI_WINDOW_DAYS}일 공시 없음'

    marked = [g for g in window if classify(g.title)]
    plain = [g for g in window if not classify(g.title)]
    trimmed = len(marked) - GONGSI_MAX_MARKED
    marked = marked[:GONGSI_MAX_MARKED]

    lines = [f'최근 {GONGSI_WINDOW_DAYS}일 공시 {len(window)}건']
    lines.append('')
    if marked:
        lines.append(f'눈여겨볼 공시 ({len(marked)}건)')
        for g in marked:
            title = re.sub(r'\s+', ' ', g.title).strip()
            lines.append(f'  {g.date:%y.%m.%d}  [{classify(g.title)}]  {title}')
        if trimmed > 0:
            lines.append(f'  … 그 앞으로 {trimmed}건 더 있음')
    else:
        lines.append('눈여겨볼 공시 없음')

    if plain:
        counter = Counter(re.sub(r'\[.*?\]', '', g.title).split('(')[0].strip()[:22]
                          for g in plain)
        top = counter.most_common(6)
        rest = sum(v for _, v in counter.most_common()[6:])
        body = ' · '.join(f'{k} {v}' for k, v in top)
        if rest:
            body += f' · 그 외 {rest}'
        lines.append('')
        lines.append(f'그 밖 ({len(plain)}건, 유형만)')
        lines.append('  ' + body)
    return '\n'.join(lines)


def gongsi_body_targets(gongsi_rows, today):
    """본문을 받아올 공시들. 화면이 이 접수번호로 /api/dart-document/ 를 부른다."""
    cut = today - timedelta(days=GONGSI_WINDOW_DAYS)
    marked = [g for g in gongsi_rows
              if g.date >= cut and classify(g.title) and 'rcpNo=' in (g.link or '')]
    out = []
    for g in marked[:GONGSI_BODY_COUNT]:
        out.append({
            'rcept_no': g.link.split('rcpNo=')[1].split('&')[0],
            'date': f'{g.date:%y.%m.%d}',
            'cat': classify(g.title),
            'title': re.sub(r'\s+', ' ', g.title).strip(),
            'link': g.link,
        })
    return out


def build_gongsi_all_prompt_vars(stock, gongsi_rows, charts_asc, today):
    """탭 단위 — 최근 공시를 통째로 보고 판단하는 프롬프트의 입력값."""
    latest = charts_asc[-1] if charts_asc else None
    base = build_gongsi_prompt_vars(stock, charts_asc, today)
    return {
        '{종목명}': base['{종목명}'],
        '{종목코드}': base['{종목코드}'],
        '{기준일}': f'{latest.date:%Y-%m-%d}' if latest else f'{today:%Y-%m-%d}',
        '{오늘날짜}': base['{오늘날짜}'],
        '{현재가}': base['{현재가}'],
        '{공시목록}': _gongsi_list(gongsi_rows, today),
        # 본문은 화면이 눌릴 때 받아 채운다
        '{공시본문}': '',
        '{주가맥락}': base['{주가맥락}'],
        '{읽는법}': base['{읽는법}'],
    }
