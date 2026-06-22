from urllib import request

from django.shortcuts import render

def login_page(request):
    return render(request, 'main/login_page.html')

def main_offer_page(request):
    return render(request, 'main/main_offer_page.html')
