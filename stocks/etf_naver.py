# -*- coding: utf-8 -*-
"""
네이버에서 ETF 한 종목의 정보를 받아온다.

쓰는 곳이 둘이다 — 날마다 도는 save_etf_info 와, 화면의 'ETF 추가' 가
부르는 views.add_etf. 예전에는 같은 긁기 코드가 양쪽에 복사되어 있었고,
네이버가 화면을 바꿨을 때 둘 다 같이 죽었다. 한 곳에 둔다.

예전에는 finance.naver.com/item/main.naver 를 CSS 셀렉터로 긁었다.
네이버가 그 화면을 Next.js 앱으로 다시 만들면서 구조가 통째로 사라졌다.
주소는 그대로 200 을 주고 셀렉터만 안 맞아 조용히 멈춰 있었다.
"""
import requests

BASIC_API = 'https://m.stock.naver.com/api/stock/{code}/basic'
ETF_API = 'https://m.stock.naver.com/api/stock/{code}/etfAnalysis'

HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                   'AppleWebKit/537.36'),
    'Referer': 'https://m.stock.naver.com/',
    'Accept': 'application/json',
}

TIMEOUT = 10


class EtfFetchFailed(Exception):
    """못 받았다. 네이버가 막혔거나 응답 모양이 바뀌었다."""


class NotAnEtf(Exception):
    """코드는 있는데 ETF 가 아니다. 사람이 잘못 넣은 것이라 다르게 알린다."""


def fetch_etf(code):
    """ETF 한 종목.

    반환:
        {'code','name','current_price','change_rate',
         'nav','market_cap','management_fee','holdings'}

    current_price 와 change_rate 는 없으면 EtfFetchFailed 다. 화면이
    보여주는 값이라 옛날 값이 남으면 사람이 틀린 숫자를 보고 판단한다.
    나머지는 ETF 마다 안 주는 것이 있어 None 으로 둔다.
    """
    basic = _get(BASIC_API, code)

    kind = basic.get('stockEndType')
    if kind != 'etf':
        name = basic.get('stockName') or code
        raise NotAnEtf(f'{name}은(는) ETF 가 아닙니다 ({kind or "알 수 없음"})')

    detail = _get(ETF_API, code)

    nav = detail.get('nav')
    raw_cap = detail.get('marketValueRaw')

    return {
        'code': code,
        'name': basic.get('stockName') or code,
        'current_price': _int(basic, 'closePrice'),
        'change_rate': _float(basic, 'fluctuationsRatio'),
        'nav': round(float(nav)) if nav is not None else None,
        # marketValueRaw 는 원 단위 정수 문자열이다. 칼럼은 억원이다.
        'market_cap': int(raw_cap) // 100_000_000 if raw_cap else None,
        'management_fee': detail.get('totalFee'),
        'holdings': _holdings(detail),
    }


def _get(url_template, code):
    url = url_template.format(code=code)
    label = url.rsplit('/', 1)[-1]
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    except Exception as e:
        raise EtfFetchFailed(f'{label} 접속 실패: {e}') from e

    # 없는 코드는 409 로 온다. 네이버가 막힌 것과 구분해 말해준다.
    if r.status_code == 409:
        raise NotAnEtf(f'{code} 는 네이버에 없는 종목코드입니다')
    if r.status_code == 404:
        raise NotAnEtf(f'{code} 의 ETF 정보가 없습니다')

    try:
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        raise EtfFetchFailed(f'{label} 조회 실패: {e}') from e

    if not isinstance(data, dict):
        raise EtfFetchFailed(f'{label} 응답 모양이 다르다: {str(data)[:120]}')
    return data


def _holdings(detail):
    """구성종목 상위 10개.

    예전 HTML 에서는 이름과 비중만 긁었다. API 는 종목코드도 준다 —
    화면의 보유 종목과 이어 볼 수 있다. 화면이 {name, ratio} 를 그대로
    쓰고 있으므로 모양을 바꾸지 않고 code 만 더한다.
    """
    out = []
    for row in (detail.get('etfTop10MajorConstituentAssets') or []):
        name = row.get('itemName')
        weight = row.get('etfWeight')
        if not name or weight is None:
            continue
        # etfWeight 는 '34.43%' 꼴의 문자열로 온다. 손대지 않는다.
        out.append({
            'name': name,
            'ratio': str(weight),
            'code': row.get('itemCode') or '',
        })
    return out[:10]


def _int(data, key):
    """'83,115' -> 83115"""
    value = data.get(key)
    if value in (None, '', '-'):
        raise EtfFetchFailed(f'{key} 가 비어 있다 (응답 모양이 바뀌었을 수 있다)')
    try:
        return int(str(value).replace(',', '').replace('+', '').strip())
    except ValueError as e:
        raise EtfFetchFailed(f'{key} 를 숫자로 읽지 못했다: {value!r}') from e


def _float(data, key):
    value = data.get(key)
    if value in (None, '', '-'):
        raise EtfFetchFailed(f'{key} 가 비어 있다 (응답 모양이 바뀌었을 수 있다)')
    try:
        return float(str(value).replace(',', '').replace('+', '').strip())
    except ValueError as e:
        raise EtfFetchFailed(f'{key} 를 숫자로 읽지 못했다: {value!r}') from e
