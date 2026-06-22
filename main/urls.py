from django.urls import path
from . import views

urlpatterns = [
    path('', views.login_page, name='login_page'),
    path('main_offer_page/', views.main_offer_page, name='main_offer_page'),
]