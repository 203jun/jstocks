# -*- coding: utf-8 -*-
"""
Claude Code 를 비대화형으로 불러 답을 받아온다.

화면의 [프롬프트] 버튼은 만들어진 글을 사람 손에 쥐여준다. 사람이
claude.ai 에 붙여넣고 답을 도로 가져와 저장한다. 그 가운데 토막을 여기서
대신한다 — 클립보드도 브라우저도 끼지 않는다.

왜 API 가 아니라 CLI 인가
    구독으로 돌아 호출마다 돈이 나가지 않는다. 대신 인증이 사람 계정에
    묶여 있어 언젠가 끊긴다(아래 ClaudeFailed 참고).

왜 claude.ai 를 브라우저로 자동 조작하지 않는가
    이용약관이 자동화된 접근을 막는다. 계정이 정지되면 아끼려던 것보다
    잃는 것이 크다. 헤드리스 CLI 는 그 용도로 만들어진 것이라 괜찮다.
"""
import json
import subprocess
import tempfile

from decouple import config


class ClaudeFailed(Exception):
    """부르지 못했거나, 불렀는데 답이 아니다."""


class ClaudeAuthFailed(ClaudeFailed):
    """로그인이 풀렸다. 사람이 다시 붙여야 한다.

        sudo -u stock claude login

    리프레시 토큰은 몇 달을 가지만 비밀번호 변경·전체 로그아웃·구독 변경
    같은 일이 생기면 그날로 끊긴다. 날짜를 예측할 수 없으므로 배치 맨 앞에서
    한 번 찔러보고(check_claude_auth) 끊겼으면 텔레그램으로 알린다.
    """


# 토큰이 아깝다고 모델을 비워두면 그날의 기본값을 따라간다. 판단을 쌓아
# 견주는 자리라 모델이 조용히 바뀌면 과거와 비교가 흔들린다. 고정한다.
DEFAULT_MODEL = 'claude-sonnet-5-5'

# 시황 프롬프트는 길어야 1만 토큰 남짓이다. 그보다 오래 걸리면 멈춘 것이다.
# 다만 웹 검색이 붙으면 검색 두 번에 몇십 초가 더 든다.
DEFAULT_TIMEOUT = 300

# 열어 줄 툴. 쉼표로 여러 개, 빈 문자열이면 전부 막는다.
#
# 검색만 연다. 프롬프트들이 "웹 검색을 사용해 기준일의 시장 뉴스를 확인하라"
# 라고 적혀 있다 — 사람이 claude.ai 에 붙여넣을 때는 검색이 되므로, 막아 두면
# '오늘 움직임' 같은 섹션이 통째로 빠져 사람이 하던 것보다 못한 답이 나온다.
#
# 파일 읽기와 명령 실행은 계속 막는다. 여기서 시키는 일은 글을 읽고 글을
# 내놓는 것뿐이고, 프롬프트에 데이터로 섞여 들어온 글이 무언가를 시키려 해도
# 할 수 있는 것이 없어야 한다. 검색은 바깥을 읽어올 뿐 이 기계를 건드리지
# 못하므로 그 선 안에 있다.
DEFAULT_TOOLS = 'WebSearch'

# 인증이 끊겼을 때 CLI 가 내보내는 말. 종료코드만으로는 네트워크 오류와
# 구분되지 않아 사람이 할 일이 다르다 — 하나는 기다리면 되고 하나는 아니다.
AUTH_HINTS = ('login', 'authenticat', 'unauthorized', 'oauth',
              'expired', 'api key', 'credit balance')


def ask(prompt, model=None, timeout=DEFAULT_TIMEOUT, tools=None):
    """프롬프트를 보내고 답과 비용을 받는다.

    반환: {'text': 답변, 'cost': USD, 'usage': {...}}
    """
    binary = config('CLAUDE_BIN', default='claude')
    model = model or config('CLAUDE_MODEL', default=DEFAULT_MODEL)
    if tools is None:
        tools = config('CLAUDE_TOOLS', default=DEFAULT_TOOLS)

    cmd = [
        binary, '-p',
        '--output-format', 'json',
        '--model', model,
        '--allowedTools', tools,
    ]

    # 빈 디렉터리에서 돌린다. 프로젝트 안에서 부르면 CLAUDE.md 와 둘레
    # 파일을 읽어 맥락에 얹는다 — 날마다 쌓아 견주는 판단에 그런 것이
    # 섞이면 안 된다. 같은 입력에 같은 조건을 준다.
    with tempfile.TemporaryDirectory() as workdir:
        try:
            # 프롬프트는 argv 가 아니라 stdin 으로 넣는다. 표가 들어가 길어서
            # argv 한도에 걸릴 수 있고, ps 에 그대로 보이지도 않는다.
            done = subprocess.run(
                cmd, input=prompt, cwd=workdir, text=True,
                capture_output=True, timeout=timeout,
            )
        except FileNotFoundError as e:
            raise ClaudeFailed(
                f'claude 를 찾지 못했습니다 ({binary}). '
                '.env 의 CLAUDE_BIN 에 전체 경로를 적어주세요.'
            ) from e
        except subprocess.TimeoutExpired as e:
            raise ClaudeFailed(f'{timeout}초 안에 답하지 않았습니다') from e

    if done.returncode != 0:
        raise _classify(done.stderr or done.stdout or f'종료코드 {done.returncode}')

    try:
        data = json.loads(done.stdout)
    except json.JSONDecodeError as e:
        raise ClaudeFailed(f'JSON 이 아닙니다: {done.stdout[:200]}') from e

    if data.get('is_error') or data.get('subtype') != 'success':
        raise _classify(str(data.get('result') or data.get('subtype')))

    text = (data.get('result') or '').strip()
    if not text:
        raise ClaudeFailed('답변이 비어 있습니다')

    return {
        'text': text,
        'cost': data.get('total_cost_usd') or 0.0,
        'usage': data.get('usage') or {},
    }


def _classify(message):
    """사람이 할 일이 다르므로 인증 문제만 따로 떼어낸다."""
    low = message.lower()
    if any(h in low for h in AUTH_HINTS):
        return ClaudeAuthFailed(message.strip()[:300])
    return ClaudeFailed(message.strip()[:300])
