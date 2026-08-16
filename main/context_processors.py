def language_code(request):
    return {"LANGUAGE_CODE": getattr(request, "LANGUAGE_CODE", "en")}
