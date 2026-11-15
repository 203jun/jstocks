# -*- coding: utf-8 -*-
import sys
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from stocks.ai_note import KINDS, basis_date, parse
from stocks.claude_cli import ClaudeAuthFailed, ClaudeFailed, ask
from stocks.logger import StockLogger
from stocks.market_signal import build_market_panel, build_prompt_vars
from stocks.models import AiNote
from stocks.prompts import (MARKET_SIGNAL_DEFAULT, MARKET_SIGNAL_KEYS,
                            get_prompt)


class Command(BaseCommand):
    help = '''
AI 판단을 받아 저장 (사람이 복사·붙여넣기 하던 자리)

화면의 [프롬프트] 버튼이 만드는 것과 똑같은 글을 서버에서 만들어 Claude 에
보내고, 돌아온 답을 AiNote 에 넣는다. 사람이 하던 것과 결과가 같다.

지금은 시황(market)만 한다. 코스피·코스닥 둘뿐이라 품질을 먼저 보기에
좋다. 종목 수급·리포트·공시는 80종목씩이라 사용량 한도를 따로 봐야 한다.

옵션:
  --kind      (선택) market (기본값)
  --key       (선택) KOSPI / KOSDAQ / all (기본값: all)
  --force     (선택) 같은 기준일에 판단이 이미 있어도 다시 받는다
  --dry-run   (선택) 프롬프트만 찍고 부르지 않는다
  --show      (선택) 받은 답을 전부 찍는다
  --log-level (선택) debug / info / warning / error (기본값: info)

예시:
  python manage.py run_ai_note --key KOSPI --dry-run
  python manage.py run_ai_note --key KOSPI --show
  python manage.py run_ai_note

바깥에서 Claude 를 부를 때 (세 토막으로 나눠 쓴다):
  python manage.py run_ai_note --list-pending
  python manage.py run_ai_note --key KOSPI --emit-prompt
  python manage.py run_ai_note --key KOSPI --basis 2026-11-13 --save-answer < 답.txt

  이 서버의 CPU 가 SSE4.2 를 지원하지 않아 claude 바이너리가 돌지 않는다
  (QEMU 가 cpu64-rhel6 로 노출한다). 그래서 부르는 일만 맥에서 하고 나머지는
  여기서 한다. 자세한 것은 docs/run_ai_note.md 에 적었다.
'''

    def add_arguments(self, parser):
        parser.add_argument('--kind', type=str, default='market',
                            help='지금은 market 만 (기본값: market)')
        parser.add_argument('--key', type=str, default='all',
                            help='KOSPI, KOSDAQ, all (기본값: all)')
        parser.add_argument('--force', action='store_true',
                            help='같은 기준일에 판단이 있어도 다시 받는다')
        parser.add_argument('--dry-run', action='store_true',
                            help='프롬프트만 찍고 부르지 않는다')
        parser.add_argument('--show', action='store_true',
                            help='받은 답을 전부 찍는다')

        # ── 바깥에서 Claude 를 부를 때 쓰는 세 토막 ──
        parser.add_argument('--list-pending', action='store_true',
                            help='오늘 판단이 필요한 대상을 "자리 대상 기준일" 로 출력')
        parser.add_argument('--emit-prompt', action='store_true',
                            help='프롬프트만 stdout 으로 출력 (부르지 않는다)')
        parser.add_argument('--save-answer', action='store_true',
                            help='stdin 으로 받은 답을 파싱해 저장')
        parser.add_argument('--basis', type=str, default=None,
                            help='기준일 YYYY-MM-DD. --save-answer 와 함께 쓴다')
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        # 세 토막 모드는 stdout 이 곧 주고받는 내용이다. 로그가 섞이면
        # 받는 쪽이 프롬프트와 로그를 구분하지 못하므로 stderr 로 보낸다.
        piped = (options['list_pending'] or options['emit_prompt']
                 or options['save_answer'])
        self.log = StockLogger(self.stderr if piped else self.stdout,
                               self.style, options, 'run_ai_note')
        self.opts = options

        kind = options['kind']
        if kind != 'market':
            raise CommandError(f'아직 market 만 할 수 있습니다 (받은 값: {kind})')
        if kind not in KINDS:
            raise CommandError(f'알 수 없는 자리: {kind}')

        key = options['key'].upper()
        markets = ['KOSPI', 'KOSDAQ'] if key == 'ALL' else [key]
        for m in markets:
            if m not in MARKET_SIGNAL_KEYS:
                raise CommandError(f'지원하지 않는 시장: {m}')

        if options['list_pending']:
            return self.list_pending(kind)
        if options['emit_prompt']:
            return self.emit_prompt(kind, markets)
        if options['save_answer']:
            return self.save_answer(kind, markets)

        self.log.info(f'AI 판단 시작 (자리: {kind}, 대상: {", ".join(markets)})')

        saved = skipped = 0
        errors = []
        total_cost = 0.0

        for market in markets:
            try:
                result = self.run_market(market)
            except ClaudeAuthFailed as e:
                # 하나가 인증으로 막히면 나머지도 다 막힌다. 80번 두드려
                # 한도만 깎지 말고 여기서 멈춘다.
                self.log.error(f'[{market}] 로그인이 풀렸습니다: {e}')
                raise CommandError(
                    'Claude 재로그인이 필요합니다. 서버에서: sudo -u stock claude login'
                )
            except ClaudeFailed as e:
                self.log.error(f'[{market}] 실패: {e}')
                errors.append(f'{market}: {e}')
                continue

            if result is None:
                skipped += 1
            else:
                saved += 1
                total_cost += result

        self.log.separator()
        tail = f' | 비용: ${total_cost:.4f}' if total_cost else ''
        if errors:
            self.log.info(f'완료 | 저장: {saved}개, 건너뜀: {skipped}개, '
                          f'오류: {len(errors)}개{tail}', success=True)
            self.log.info('')
            self.log.info('[오류 목록]')
            for e in errors:
                self.log.error(f'  {e}')
        else:
            self.log.info(f'완료 | 저장: {saved}개, 건너뜀: {skipped}개{tail}',
                          success=True)

        # 한 건도 못 받았으면 비정상 종료로 끝낸다. 배치가 이 종료코드를 보고
        # 텔레그램에 실어 보낸다 (batch_lib.sh).
        if errors and saved == 0:
            raise CommandError(f'AI 판단을 한 건도 받지 못했습니다 ({len(errors)}개 전부)')

    # ── 바깥에서 Claude 를 부를 때 쓰는 세 토막 ──────────────────────
    #
    # 이 서버에서는 claude 바이너리가 돌지 않는다. CPU 가 SSE4.2 를 지원하지
    # 않아서다(QEMU 가 cpu64-rhel6 로 노출한다). 그래서 부르는 일만 맥에서
    # 하고, 프롬프트를 만들고 답을 저장하는 일은 여기서 그대로 한다.
    #
    # 셋 다 stdout 으로는 주고받는 내용만 내보낸다. 로그는 stderr 로 간다.

    def list_pending(self, kind):
        """오늘 판단이 필요한 대상. 한 줄에 '자리 대상 기준일'.

        기준일을 같이 주는 까닭: 프롬프트를 뽑은 뒤 답을 저장하기까지 몇 분이
        걸리는데 그사이 새 데이터가 들어오면 기준일이 바뀐다. 그러면 옛 데이터로
        내린 판단이 새 날짜에 붙는다. 뽑을 때의 날짜를 들고 다녀 그것을 막는다.
        """
        for market in ['KOSPI', 'KOSDAQ']:
            date = basis_date(kind, market)
            if not date:
                self.log.warning(f'[{market}] 데이터가 없어 기준일을 정할 수 없습니다')
                continue
            if AiNote.objects.filter(kind=kind, key=market, date=date).exists():
                self.log.debug(f'[{market}] {date} 판단이 이미 있습니다')
                continue
            self.stdout.write(f'{kind} {market} {date:%Y-%m-%d}')

    def emit_prompt(self, kind, markets):
        """프롬프트만 내보낸다. 받는 쪽이 그대로 claude 에 넘긴다."""
        if len(markets) != 1:
            raise CommandError('--emit-prompt 는 --key 로 하나만 지정해야 합니다')
        market = markets[0]

        date = basis_date(kind, market)
        if not date:
            raise CommandError(f'[{market}] 데이터가 없어 기준일을 정할 수 없습니다')

        self.log.info(f'[{market}] 기준일 {date} 프롬프트 생성')
        # write 는 줄바꿈을 덧붙이므로 ending='' 로 원문 그대로 내보낸다.
        self.stdout.write(self.build_prompt(market), ending='')

    def save_answer(self, kind, markets):
        """stdin 으로 받은 답을 파싱해 저장한다."""
        if len(markets) != 1:
            raise CommandError('--save-answer 는 --key 로 하나만 지정해야 합니다')
        market = markets[0]

        content = sys.stdin.read().strip()
        if not content:
            raise CommandError('stdin 으로 받은 답이 비어 있습니다')

        date = basis_date(kind, market)
        if not date:
            raise CommandError(f'[{market}] 데이터가 없어 기준일을 정할 수 없습니다')

        if self.opts['basis']:
            try:
                asked = datetime.strptime(self.opts['basis'], '%Y-%m-%d').date()
            except ValueError:
                raise CommandError(f'--basis 형식이 잘못됐습니다: {self.opts["basis"]} (YYYY-MM-DD)')
            if asked != date:
                # 프롬프트를 뽑은 뒤 새 데이터가 들어왔다. 판단은 옛 데이터로
                # 내린 것이므로 그 날짜에 붙인다. 새 날짜는 다음 차례에 받는다.
                self.log.warning(f'[{market}] 기준일이 그사이 바뀌었습니다 '
                                 f'({asked} -> {date}). 판단을 뽑을 때의 날짜인 '
                                 f'{asked} 에 저장합니다')
            date = asked

        existing = AiNote.objects.filter(kind=kind, key=market, date=date).first()
        if existing and not self.opts['force']:
            self.log.info(f'[{market}] {date} 판단이 이미 있습니다 — 건너뜁니다 '
                          f'(덮어쓰려면 --force)')
            return

        auto = parse(content)
        if not auto['headline']:
            self.log.warning(f'[{market}] 한 줄 결론을 뽑지 못했습니다 '
                             f'(답변 형식 확인 필요). 본문은 저장합니다')
        if not auto['stance']:
            self.log.warning(f'[{market}] 매매 스탠스를 뽑지 못했습니다')

        AiNote.objects.update_or_create(
            kind=kind, key=market, date=date,
            defaults={
                'headline': auto['headline'][:300],
                'stance': auto['stance'],
                'content': content,
            },
        )
        verb = '덮어씀' if existing else '저장'
        self.log.info(f'[{market}] {date} {verb} | {auto["stance"] or "(스탠스 없음)"} '
                      f'| {auto["headline"][:60] or "(결론 없음)"}', success=True)

    # ── 서버에서 직접 부를 때 (이 서버에서는 CPU 때문에 못 쓴다) ────────

    def run_market(self, market):
        """한 시장. 저장했으면 비용, 건너뛰었으면 None."""
        self.log.separator()
        self.log.info(f'[{market}] 처리 시작')

        # 기준일은 '지금 날짜' 가 아니라 '판단의 근거가 된 데이터의 날짜' 다.
        # 토요일에 돌려도 데이터는 금요일 것이라 저장일로 잡으면 어긋난다.
        # 화면의 저장 경로(views.ai_note_save)와 같은 값을 쓴다.
        date = basis_date('market', market)
        if not date:
            raise ClaudeFailed('데이터가 아직 없어 기준일을 정할 수 없습니다')

        existing = AiNote.objects.filter(kind='market', key=market, date=date).first()
        if existing and not self.opts['force']:
            self.log.info(f'[{market}] {date} 판단이 이미 있습니다 — 건너뜁니다 '
                          f'(다시 받으려면 --force)')
            return None

        prompt = self.build_prompt(market)
        self.log.debug(f'[{market}] 프롬프트 {len(prompt):,}자')

        if self.opts['dry_run']:
            self.log.separator('-')
            self.stdout.write(prompt)
            self.log.separator('-')
            self.log.info(f'[{market}] --dry-run 이라 부르지 않았습니다')
            return None

        answer = ask(prompt)
        self.log.info(f'[{market}] 응답 {len(answer["text"]):,}자 '
                      f'| ${answer["cost"]:.4f} | {_usage(answer["usage"])}')

        if self.opts['show']:
            self.log.separator('-')
            self.stdout.write(answer['text'])
            self.log.separator('-')

        # 한 줄 결론과 스탠스를 뽑는다. 형식을 어기면 빈 값이 오는데, 그래도
        # 본문은 저장한다 — 화면에서 사람이 채울 수 있다.
        auto = parse(answer['text'])
        if not auto['headline']:
            self.log.warning(f'[{market}] 한 줄 결론을 뽑지 못했습니다 '
                             f'(답변 형식 확인 필요). 본문은 저장합니다')
        if not auto['stance']:
            self.log.warning(f'[{market}] 매매 스탠스를 뽑지 못했습니다')

        AiNote.objects.update_or_create(
            kind='market', key=market, date=date,
            defaults={
                'headline': auto['headline'][:300],
                'stance': auto['stance'],
                'content': answer['text'],
            },
        )
        verb = '덮어씀' if existing else '저장'
        self.log.info(f'[{market}] {date} {verb} | {auto["stance"] or "(스탠스 없음)"} '
                      f'| {auto["headline"][:60] or "(결론 없음)"}', success=True)
        return answer['cost']

    def build_prompt(self, market):
        """화면의 fillPrompt() 와 같은 치환을 서버에서 한다.

        템플릿은 설정에서 고칠 수 있다(SystemSetting). 고친 것이 있으면
        그것을, 없으면 코드 기본값을 쓴다 — 화면과 같은 글이 나가야 한다.
        """
        panel = build_market_panel(market)
        template = get_prompt(MARKET_SIGNAL_KEYS[market], MARKET_SIGNAL_DEFAULT)
        variables = build_prompt_vars(market, panel, datetime.now().date())

        text = template
        for name, value in variables.items():
            # 변수명에 정규식 특수문자({})가 있어 치환으로 바꾼다
            text = text.replace(name, str(value))
        return text


def _usage(u):
    return (f'입력 {u.get("input_tokens", 0):,} '
            f'캐시생성 {u.get("cache_creation_input_tokens", 0):,} '
            f'캐시읽기 {u.get("cache_read_input_tokens", 0):,} '
            f'출력 {u.get("output_tokens", 0):,}')
