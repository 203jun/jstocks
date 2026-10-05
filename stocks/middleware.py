from django.shortcuts import redirect
from django.conf import settings


class LoginRequiredMiddleware:
    """모든 페이지에 로그인을 필수로 요구하는 미들웨어"""

    def __init__(self, get_response):
        self.get_response = get_response
        self.login_url = settings.LOGIN_URL
        # 로그인 없이 열어둘 경로. 끝 슬래시를 떼고 적는다 — 비교할 때 둘 다 받는다.
        #
        # admin 은 넣지 않는다. 자기 로그인 화면이 따로 있어 안전하긴 하지만,
        # 그 화면이 보이는 것 자체가 두드릴 문이 하나 더 있는 것이다. 빼 두면
        # /login/ 으로 먼저 들어온 뒤에야 admin 이 열린다.
        self.open_prefixes = [
            f'/{self.login_url}',
            '/ontoo',   # 동료와 같이 보는 공유 페이지 (읽기 전용)
        ]

    def _is_open(self, path):
        """열어둔 경로인가.

        끝 슬래시가 없는 꼴도 열어야 한다. Django 의 APPEND_SLASH 는
        CommonMiddleware 가 '응답이 404 일 때' 돌려주는 것인데, 여기서 먼저
        로그인으로 돌려보내면 404 가 될 일이 없어 슬래시가 붙지 않는다.
        그래서 /ontoo 를 치면 공유 페이지가 아니라 로그인 화면이 떴다.

        그렇다고 startswith 하나로 비교하면 /ontoostocks/ 처럼 이어붙인
        주소까지 열린다. 그래서 '같은가' 와 '그 아래인가' 를 따로 본다.
        """
        return any(path == p or path.startswith(p + '/') for p in self.open_prefixes)

    def __call__(self, request):
        if not request.user.is_authenticated and not self._is_open(request.path):
            return redirect(self.login_url)

        return self.get_response(request)
