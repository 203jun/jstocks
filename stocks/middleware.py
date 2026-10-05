from django.shortcuts import redirect
from django.conf import settings


class LoginRequiredMiddleware:
    """모든 페이지에 로그인을 필수로 요구하는 미들웨어"""

    def __init__(self, get_response):
        self.get_response = get_response
        self.login_url = settings.LOGIN_URL
        # 로그인 없이 열어둘 경로 (startswith 매칭이므로 끝에 '/' 를 꼭 붙인다)
        #
        # admin 은 넣지 않는다. 자기 로그인 화면이 따로 있어 안전하긴 하지만,
        # 그 화면이 보이는 것 자체가 두드릴 문이 하나 더 있는 것이다. 빼 두면
        # /login/ 으로 먼저 들어온 뒤에야 admin 이 열린다 — 쓰는 데 지장은 없고
        # 바깥에서 보이는 문이 하나 줄어든다.
        self.open_urls = [
            f'/{self.login_url}/',
            '/ontoo/',   # 동료와 같이 보는 공유 페이지 (읽기 전용)
        ]

    def __call__(self, request):
        if not request.user.is_authenticated:
            if not any(request.path.startswith(url) for url in self.open_urls):
                return redirect(self.login_url)

        return self.get_response(request)
