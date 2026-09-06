from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.urls import reverse
from django_celery_results.models import TaskResult
from django.utils.html import format_html
from .models import (
    Client, Order, RecoveryAttempt, RecoverySession, Transport,
    FactoryOrder, ClientOrder,
    DepositType, DepositFactory, DepositClient,
    UserProfile, 
)
import json

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

    list_display = ['__str__', 'is_paid', 'payment_due_by', 'is_reminder_sent']
    list_filter = ['is_paid', 'is_reminder_sent', 'deposit_type']
    # factory_order.__str__ touches factory_order.order.__str__ too — grab
    # all 3 levels in one query instead of 3 queries per row.
    list_select_related = ['factory_order', 'factory_order__order', 'deposit_type']
    
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
    
    list_display = ['__str__', 'is_paid', 'payment_due_by', 'is_reminder_sent']
    list_filter = ['is_paid', 'is_reminder_sent', 'deposit_type']
    list_select_related = ['client_order', 'client_order__order', 'deposit_type']

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
    
    list_display = ['__str__', 'courier', 'delivery_date', 'is_reminder_sent']
    list_filter = ['is_reminder_sent']
    list_select_related = ['order', 'order__client']
    
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
    
    list_display = ['__str__', 'status', 'production_start_date', 'production_end_date']
    list_filter = ['status', 'is_furniture_reminder_sent', 'is_package_clarification_reminder_sent']
    list_select_related = ['order', 'order__client']
    
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
    
admin.site.unregister(TaskResult) # unregister the auto-registered TaskResultAdmin by django_celery_result

class RecoveryAttemptInline(admin.TabularInline):
    model = RecoveryAttempt
    extra = 0
    can_delete = False
    readonly_fields = ("created_at", "status", "ip_address", "detail")
    
@admin.register(TaskResult)
class CustomTaskResultAdmin(admin.ModelAdmin):
    list_display = ["task_name", "status", "date_done", "result_summary"]

    @admin.display(description="Result")
    def result_summary(self, obj):
        if not obj.result:
            return "—"

        # Decode the result. It may be JSON-encoded more than once.
        result = obj.result

        for _ in range(2):
            if not isinstance(result, str):
                break

            try:
                result = json.loads(result)
            except (json.JSONDecodeError, TypeError):
                break

        warning = ""

        if (
            obj.task_name == "main.tasks.check_reminders_task"
            and isinstance(result, dict)
            and result.get("pushed", 0) > 0
        ):
            warning = format_html(
                ' <span title="{} reminders pushed" '
                'style="color: #ffc107; font-size: 16px; '
                'font-weight: bold; cursor: help;">⚠️</span>',
                result["pushed"],
            )

        return format_html(
            '<span title="{}">ⓘ</span>{}',
            obj.result,
            warning,
        )    
    
@admin.register(RecoverySession)
class RecoverySessionAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "started_at", "finished_at", "result"]
    readonly_fields = ["id", "user", "started_at", "finished_at", "result"]
    list_filter = ["result", "started_at", "finished_at"]
    search_fields = ["user__username", "user__email"]
    list_select_related = ["user"]
    
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
