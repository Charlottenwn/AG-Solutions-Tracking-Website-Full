from django.urls import path
from . import views

urlpatterns = [
    path('', views.login_page, name='login_page'),
    path('main_offer_page/', views.main_offer_page, name='main_offer_page'),
    path('mark_reminder_sent/<str:kind>/<int:factory_order_id>/', views.mark_reminder_sent, name='mark_reminder_sent'),
]