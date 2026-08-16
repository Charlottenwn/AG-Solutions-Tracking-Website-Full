from django.urls import path
from . import views

urlpatterns = [
    path('', views.login_page, name='login_page_root'),
    path('login_page/', views.login_page, name='login_page'),
    path('main_offer_page/', views.main_offer_page, name='main_offer_page'),
    path('mark_reminder_sent/<str:kind>/<int:factory_order_id>/', views.mark_reminder_sent, name='mark_reminder_sent'),
    path('recover_password_request_page/', views.recover_password_request, name='recover_password_request_page'),
    path('set_new_password_page/', views.set_new_password, name='set_new_password_page'),
    path('recover_password_verify_page/', views.recover_password_verify, name='recover_password_verify_page'),
    path('mark_transport_reminder_sent/<int:order_id>/', views.mark_transport_reminder_sent, name='mark_transport_reminder_sent'),
    path('api/latest_sync/', views.latest_sync_time, name='latest_sync_time'),
    path('toggle_language/', views.toggle_language, name='toggle_language'),
]
