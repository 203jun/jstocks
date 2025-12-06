from django.shortcuts import redirect
from django.conf import settings


class LoginRequiredMiddleware:
    """모든 페이지에 로그인을 필수로 요구하는 미들웨어"""

    def __init__(self, get_response):
        self.get_response = get_response
        self.login_url = settings.LOGIN_URL
        self.open_urls = [
            f'/{self.login_url}/',
            '/admin/',
        ]

    def __call__(self, request):
        if not request.user.is_authenticated:
            if not any(request.path.startswith(url) for url in self.open_urls):
                return redirect(self.login_url)

        return self.get_response(request)
