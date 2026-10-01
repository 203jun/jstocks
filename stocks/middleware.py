from django.shortcuts import redirect
from django.conf import settings


class LoginRequiredMiddleware:
    """모든 페이지에 로그인을 필수로 요구하는 미들웨어"""

    def __init__(self, get_response):
        self.get_response = get_response
        self.login_url = settings.LOGIN_URL
        # 로그인 없이 열어둘 경로 (startswith 매칭이므로 끝에 '/' 를 꼭 붙인다)
        self.open_urls = [
            f'/{self.login_url}/',
            '/admin/',
            '/ontoo/',   # 동료와 같이 보는 공유 페이지 (읽기 전용)
        ]

    def __call__(self, request):
        if not request.user.is_authenticated:
            if not any(request.path.startswith(url) for url in self.open_urls):
                return redirect(self.login_url)

        return self.get_response(request)
