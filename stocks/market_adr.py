# -*- coding: utf-8 -*-
"""
ADR(등락비율) 수집 — adrinfo.kr

adrinfo.kr/chart 는 별도 API 없이 HTML 안에 인라인 JS 배열로 전체 이력을 담고 있다.
한 번 호출하면 KOSPI/KOSDAQ 각 7년치(2019-08~)가 통째로 온다.

    const kospi_adr=[[1565708400000, 75.17], [1565881200000, 72.71], ... ];
    const kosdaq_adr=[[1565708400000, 85.34], ... ];

수집 시 지켜야 할 것 두 가지:
1. HTTPS 불가 — https 로 붙으면 TLS 핸드셰이크가 실패한다(tlsv1 alert internal error).
   반드시 http 로 요청한다.
2. 기본 User-Agent 는 403 — 브라우저 UA 를 넣어야 200 이 온다.

타임스탬프는 밀리초이며 KST 자정 기준이다. UTC 로 해석하면 날짜가 하루씩 밀린다.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import requests

ADR_CHART_URL = 'http://adrinfo.kr/chart'

# 사이트가 기본 UA 를 막아 둬서 브라우저 UA 가 필요하다 (네이버 수집과 같은 방식)
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/126.0 Safari/537.36'
)

KST = timezone(timedelta(hours=9))

# 시장 -> 페이지 안의 JS 변수명
ADR_VARIABLES = {
    'KOSPI': 'kospi_adr',
    'KOSDAQ': 'kosdaq_adr',
}


class AdrFetchError(Exception):
    """ADR 수집/파싱 실패 (사이트 구조 변경 포함)"""


def _parse_series(html, variable):
    """인라인 JS 배열 하나를 {date: Decimal} 로 파싱"""
    match = re.search(rf'{variable}\s*=\s*(\[.*?\])\s*;', html, re.S)
    if not match:
        raise AdrFetchError(f'페이지에서 {variable} 배열을 찾지 못했습니다 (사이트 구조 변경?)')

    # 배열 끝에 trailing comma 가 있어 그대로는 JSON 이 아니다
    body = re.sub(r',\s*\]$', ']', match.group(1).strip())
    try:
        rows = json.loads(body)
    except ValueError as exc:
        raise AdrFetchError(f'{variable} 배열 파싱 실패: {exc}') from exc

    series = {}
    for row in rows:
        if not isinstance(row, list) or len(row) != 2:
            continue
        timestamp, value = row
        if value is None:  # 미래 날짜 자리(placeholder)
            continue
        date = datetime.fromtimestamp(timestamp / 1000, KST).date()
        series[date] = Decimal(str(value))

    if not series:
        raise AdrFetchError(f'{variable} 에 유효한 값이 없습니다')
    return series


def fetch_adr(timeout=20):
    """
    KOSPI/KOSDAQ 일별 ADR 전체 이력을 가져온다.

    Returns:
        {'KOSPI': {date: Decimal, ...}, 'KOSDAQ': {...}}

    Raises:
        AdrFetchError: 요청 실패 또는 파싱 실패
    """
    try:
        response = requests.get(
            ADR_CHART_URL,
            headers={'User-Agent': USER_AGENT},
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise AdrFetchError(f'{ADR_CHART_URL} 요청 실패: {exc}') from exc

    return {
        market: _parse_series(response.text, variable)
        for market, variable in ADR_VARIABLES.items()
    }
