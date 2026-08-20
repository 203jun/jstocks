# -*- coding: utf-8 -*-
"""
변수 목록(research_vars)과 실제 치환(tradeMap)이 어긋나지 않는지 본다.

목록은 사람이 읽으라고 있는 것이고 치환은 템플릿의 JS 가 한다. 한쪽만
고치면 "쓸 수 있다고 적혀 있는데 안 채워지는" 변수가 생긴다. 그건 설명이
없느니만 못하다.
"""
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from stocks import research_vars

TEMPLATE = 'stocks/templates/stocks/question_report_detail.html'


class Command(BaseCommand):
    help = '리서치 변수 목록이 실제 치환과 맞는지 확인'

    def handle(self, *args, **options):
        path = Path(settings.BASE_DIR) / TEMPLATE
        text = path.read_text()

        # tradeMap 의 키들
        in_map = set(re.findall(r"^\s*'([^']+)':\s*_orEmpty", text, re.M))
        # 따로 replace 되는 것들
        in_map |= set(re.findall(r"prompt\.replace\(/\\\{([^\\(]+)\\\}/g", text))
        if '{사업보고서' in text:
            in_map.add('사업보고서')


        listed = set(research_vars.all_names())

        missing = sorted(listed - in_map)          # 적혀 있는데 안 채워진다
        extra = sorted(in_map - listed)            # 채워지는데 안 적혀 있다

        self.stdout.write(f'목록 {len(listed)}개 · 치환 {len(in_map)}개')
        if missing:
            self.stdout.write(self.style.ERROR(
                f'  적혀 있는데 치환 안 됨 {len(missing)}: ' + ' · '.join(missing)))
        if extra:
            self.stdout.write(self.style.WARNING(
                f'  치환되는데 목록에 없음 {len(extra)}: ' + ' · '.join(extra)))
        if not missing and not extra:
            self.stdout.write(self.style.SUCCESS('  어긋난 것 없음'))
