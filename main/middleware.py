from django.utils import translation
from .models import SiteSettings


class SiteLanguageMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        language = SiteSettings.get_language()
        translation.activate(language)
        request.LANGUAGE_CODE = language
        response = self.get_response(request)
        translation.deactivate()
        return response
