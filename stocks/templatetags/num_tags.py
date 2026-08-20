# -*- coding: utf-8 -*-
"""
숫자를 사람이 읽는 단위로.

    {% load num_tags %}
    {{ stock.market_cap|eok }}      12803350  ->  1,280조
                                       24288  ->  2조 4,288억
                                        4321  ->  4,321억
"""
from django import template
from django.contrib.humanize.templatetags.humanize import intcomma

register = template.Library()

JO = 10_000  # 1조 = 10,000억


@register.filter
def eok(value):
    """
    억 단위 숫자를 조·억으로 나눠 쓴다.

    삼성전자 시총이 12,803,350억으로 찍히고 있었다. 자릿수를 세어야 크기를
    알 수 있는 숫자는 안 읽게 된다.

    조 단위가 커지면 억은 버린다 — 1,280조에서 3,350억은 소수점 아래다.
    """
    if value in (None, ''):
        return '-'
    try:
        n = int(value)
    except (TypeError, ValueError):
        return value
    sign = '-' if n < 0 else ''
    n = abs(n)
    if n < JO:
        return f'{sign}{intcomma(n)}억'
    jo, rest = divmod(n, JO)
    if jo >= 100 or not rest:
        return f'{sign}{intcomma(jo)}조'
    return f'{sign}{intcomma(jo)}조 {intcomma(rest)}억'
