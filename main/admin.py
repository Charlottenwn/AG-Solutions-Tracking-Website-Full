from django.contrib import admin
from .models import (
    Client, Order, Transport,
    FactoryOrder, ClientOrder,
    DepositType, DepositFactory, DepositClient
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

admin.site.register(Client)
admin.site.register(Order)
admin.site.register(ClientOrder)
admin.site.register(DepositType)
# Register your models here.
