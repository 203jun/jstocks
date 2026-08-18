# -*- coding: utf-8 -*-
"""
'프롬프트' 버튼과 그 짝인 '설정' 링크.

버튼만 있으면 프롬프트를 고치러 갈 길이 없다. 설정 화면에 들어가 탭 열댓 개
중에서 맞는 것을 찾아야 했다. 두 동작은 늘 붙어 다니므로 한 태그로 묶는다.

    {% prompt_pair "prompt_briefing" id="btnCopyBriefingPrompt" %}

복사 동작은 각 화면의 JS 가 id/class 로 잡아서 붙인다. 이 태그는 겉모습과
설정으로 가는 길만 책임진다.
"""
from django import template
from django.urls import reverse
from django.utils.html import format_html

from ..prompts import PROMPT_PANELS

register = template.Library()


@register.simple_tag
def prompt_pair(key, id='', cls='', label='프롬프트'):
    panel = PROMPT_PANELS.get(key, '')
    settings_url = reverse('stocks:settings')
    return format_html(
        '<span class="prompt-badge{}" role="button"{}>{}</span>'
        '<a class="prompt-edit" href="{}#{}" target="_blank" rel="noopener" '
        'title="이 프롬프트 편집">설정</a>',
        f' {cls}' if cls else '',
        format_html(' id="{}"', id) if id else '',
        label, settings_url, panel,
    )
