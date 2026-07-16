from django.urls import path
from . import views

urlpatterns = [
    path('', views.login_page, name='login_page'),
    path('main_offer_page/', views.main_offer_page, name='main_offer_page'),
    path('mark_reminder_sent/<str:kind>/<int:factory_order_id>/', views.mark_reminder_sent, name='mark_reminder_sent'),
    path('recover_password_request_page/', views.recover_password_request_page, name='recover_password_request_page'),
    path('set_new_password_page/', views.set_new_password_page, name='set_new_password_page'),
    path('recover_password_verify_page/', views.recover_password_verify_page, name='recover_password_verify_page'),
]