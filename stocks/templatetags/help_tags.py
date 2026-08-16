# -*- coding: utf-8 -*-
"""
{% help_icon "키" %} — 눌러서 설명을 보는 ⓘ 아이콘.

설명 문구는 stocks/help_texts.py 에 있고, 팝업 자체는 base.html 이 갖고 있다.
그래서 어느 템플릿에서든 아래 두 줄이면 끝난다.

    {% load help_tags %}
    ... 제목 옆에 {% help_icon "events" %}

시장별로 임계값이 다른 항목은 두 번째 인자로 시장 코드를 준다.

    {% help_icon "disparity" market_code %}
"""
from django import template
from django.utils.html import format_html

from ..help_texts import HELP_TEXTS

register = template.Library()


@register.simple_tag
def help_icon(key, market=None):
    item = HELP_TEXTS.get(key)
    if not item:
        return ''
    body = item['body']
    if callable(body):
        body = body(market)
    # button 이 아니라 span 인 이유: 이미 button 인 요소(접기 헤더 등) 안에도
    # 붙을 수 있는데, button 중첩은 HTML 파서가 끊어낸다.
    return format_html(
        '<span class="hlp" role="button" tabindex="0" data-help-title="{}"'
        ' data-help-body="{}" aria-label="{} 설명">ⓘ</span>',
        item['title'], body, item['title'],
    )
