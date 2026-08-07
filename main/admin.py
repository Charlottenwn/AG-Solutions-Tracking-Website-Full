from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.urls import reverse
from django_celery_results.models import TaskResult
from django.utils.html import format_html
from .models import (
    ApiToken, Client, Order, RecoveryAttempt, RecoverySession, Transport,
    FactoryOrder, ClientOrder,
    DepositType, DepositFactory, DepositClient,
    UserProfile, 
)

@admin.register(DepositFactory)
class DepositFactoryAdmin(admin.ModelAdmin):
    fields = [
        'factory_order',
        'deposit_type',
        'is_paid',
        'payment_due_by',
        'is_reminder_sent',
        'reminder_date',
    ]

    def get_readonly_fields(self, request, obj=None):
        readonly = ['reminder_date'] # always readonly
        if obj:
            if obj.is_paid:
                readonly += ['payment_due_by', 'deposit_type']
            if obj.is_reminder_sent:
                readonly += ['reminder_date']
        return readonly


@admin.register(DepositClient)
class DepositClientAdmin(admin.ModelAdmin):
    fields = [
        'client_order',
        'deposit_type',
        'is_paid',
        'payment_due_by',
        'is_reminder_sent',
        'reminder_date',
    ]
    
    def get_readonly_fields(self, request, obj=None):
        readonly = ['reminder_date']  # always readonly
        if obj:
            if obj.is_paid:
                readonly += ['payment_due_by', 'deposit_type']
            if obj.is_reminder_sent:
                readonly += ['reminder_date']
        return readonly


@admin.register(Transport)
class TransportAdmin(admin.ModelAdmin):
    fields = [
        'order',
        'courier',
        'delivery_address',
        'delivery_price',
        'delivery_date',
        'is_reminder_sent',
        'reminder_date',
    ]
    
    def get_readonly_fields(self, request, obj=None):
        readonly = ['reminder_date']  # always readonly
        if obj:
            if obj.is_reminder_sent:
                readonly += ['reminder_date']
        return readonly
    
@admin.register(FactoryOrder)
class FactoryOrderAdmin(admin.ModelAdmin):
    fields = [
        'order',
        'factory_name',
        'factory_order_number',
        'order_amount',
        'production_start_date',
        'production_end_date',
        'status',
        'furniture_reminder_date',
        'is_furniture_reminder_sent',
        'package_clarification_reminder_date',
        'is_package_clarification_reminder_sent',
    ]
    
    def get_readonly_fields(self, request, obj=None):
        readonly = ['furniture_reminder_date', 'package_clarification_reminder_date']  # always readonly
        if obj:
            if obj.is_furniture_reminder_sent:
                readonly += ['furniture_reminder_date']
            if obj.is_package_clarification_reminder_sent:
                readonly += ['package_clarification_reminder_date']
        return readonly

class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = "Profile"


class CustomUserAdmin(UserAdmin):
    inlines = [UserProfileInline]
    
@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    list_display = ["label", "token", "is_active", "last_used_at", "created_at"]
    readonly_fields = ["token", "last_used_at", "created_at"]

admin.site.unregister(TaskResult) # unregister the auto-registered TaskResultAdmin by django_celery_result
   
@admin.register(TaskResult)
class CustomTaskResultAdmin(admin.ModelAdmin):
    list_display = ["task_name", "status", "date_done", "result_summary"]

    def result_summary(self, obj):
        if not obj.result:
            return "—"
        return format_html('<span title="{}">ⓘ</span>', obj.result)

    result_summary.short_description = "Result" 

class RecoveryAttemptInline(admin.TabularInline):
    model = RecoveryAttempt
    extra = 0
    can_delete = False
    readonly_fields = ("created_at", "status", "ip_address", "detail")
    
    def has_add_permission(self, request, obj=None):
        return False
    
@admin.register(RecoverySession)
class RecoverySessionAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "started_at", "finished_at", "result"]
    readonly_fields = ["id", "user", "started_at", "finished_at", "result"]
    list_filter = ["result", "started_at", "finished_at"]
    search_fields = ["user__username", "user__email"]
    
    inlines = [RecoveryAttemptInline]
    
    ordering = ["-started_at"]
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False

admin.site.register(Client)
admin.site.register(Order)
admin.site.register(ClientOrder)
admin.site.register(DepositType)
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)
