# -*- coding: utf-8 -*-
"""
'프롬프트' 버튼과 그 짝인 편집(⚙).

버튼만 있으면 프롬프트를 고치러 갈 길이 없다. 설정 화면에 들어가 탭 열댓 개
중에서 맞는 것을 찾아야 했다. 두 동작은 늘 붙어 다니므로 한 덩어리로 묶는다.

    {% prompt_pair "prompt_briefing" id="btnCopyBriefingPrompt" %}

복사 동작은 각 화면의 JS 가 id/class 로 잡아서 붙인다. 이 태그는 겉모습과
편집으로 가는 길만 책임진다.

⚙ 는 두 가지로 동작한다.
  inline=True   그 자리에서 편집 창을 연다 (data-prompt-edit)
  inline=False  설정 화면의 해당 패널로 보낸다 (링크)
설정 메뉴는 없어질 예정이라 inline 이 가는 방향이다. 아직 편집 창을 붙이지
않은 화면만 링크로 남는다.
"""
from django import template
from django.urls import reverse
from django.utils.html import format_html

from ..prompts import PROMPT_PANELS

register = template.Library()


@register.simple_tag
def prompt_pair(key, id='', cls='', label='프롬프트', inline=False, source=''):
    # source 는 '요약' 프롬프트가 어느 입력칸을 원문으로 쓸지 가리킨다.
    main = format_html(
        '<span class="{}" role="button"{}{}>{}</span>',
        cls or 'pp-main',
        format_html(' id="{}"', id) if id else '',
        format_html(' data-source="{}"', source) if source else '',
        label,
    )
    if inline:
        gear = format_html(
            '<button type="button" data-prompt-edit="{}" title="이 프롬프트 편집">⚙</button>', key)
    else:
        gear = format_html(
            '<a href="{}#{}" target="_blank" rel="noopener" title="이 프롬프트 편집">⚙</a>',
            reverse('stocks:settings'), PROMPT_PANELS.get(key, ''))
    return format_html('<span class="prompt-pair">{}{}</span>', main, gear)


@register.simple_tag
def prompt_gear(key, title='이 프롬프트 편집'):
    """복사 버튼이 따로 노는 자리(공시 표처럼 행마다 버튼이 있는 곳)의 ⚙ 하나."""
    return format_html(
        '<span class="prompt-pair">'
        '<button type="button" data-prompt-edit="{}" title="{}">⚙</button></span>',
        key, title)
