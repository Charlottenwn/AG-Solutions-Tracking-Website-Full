from django.utils import timezone
from django.db import models
from django.conf import settings
from gunicorn.config import User
from gunicorn.config import User
from .choices import Status, PaymentType
from .constants import REMINDER_DAYS_BEFORE
import secrets as secrets_module

class Status_recovery(models.TextChoices):
    INITIATED = "initiated", "Initiated"
    CODE_VERIFIED = "code_verified", "Code verified"
    PASSWORD_RESET = "password_reset", "Password reset completed"
    FAILED_LOCKOUT = "failed_lockout", "Failed — locked out"
    FAILED_NO_PHONE = "failed_no_phone", "Failed — no phone on file"
    FAILED_INVALID_CODE = "failed_invalid_code", "Failed — invalid/expired code"
    FAILED_SMS_ERROR = "failed_sms_error", "Failed — SMS send error"
    
class Status(models.TextChoices):
    PENDING = "pending", "Pending"
    IN_PROGRESS = "in_progress", "In Progress"
    COMPLETED = "completed", "Completed"
    
class Status_recovery_session(models.TextChoices):
    ACTIVE = "active", "Active"
    SUCCESS = "success", "Success"
    FAILED = "failed", "Failed"
    
class PaymentType(models.TextChoices):
    FULL = "full", "Visa suma"
    DEPOSIT = "deposit", "Avansas"
    AFTER_DELIVERY = "after_delivery", "Po pristatymo"
    
class Client(models.Model):
    client_name = models.CharField(max_length=100)
    client_contact_number = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return self.client_name
    
class Order(models.Model):
    client = models.ForeignKey(Client, on_delete=models.PROTECT)
    contract_number = models.CharField(max_length=50, unique=True)
    country = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.contract_number
    
class Transport(models.Model):
    order = models.OneToOneField(Order, on_delete=models.CASCADE)
    courier = models.CharField(max_length=100, blank=True)
    delivery_address = models.CharField(max_length=255, blank=True)
    delivery_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    delivery_date = models.DateField(null=True, blank=True)
    is_reminder_sent = models.BooleanField(default=False)
    reminder_date = models.DateField(null=True, blank=True, editable=False)

    class Meta:
        verbose_name = 'Transport'
        verbose_name_plural = 'Transports'

    def save(self, *args, **kwargs):
        if self.delivery_date:
            from django.utils import timezone
            from datetime import timedelta
            days_until_delivery = (self.delivery_date - timezone.now().date()).days
            if days_until_delivery <= REMINDER_DAYS_BEFORE:
                self.reminder_date = timezone.now().date()
            else:
                self.reminder_date = self.delivery_date - timedelta(days=REMINDER_DAYS_BEFORE)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Transport for {self.order}"
    
class FactoryOrder(models.Model):

    order=models.ForeignKey(Order, on_delete=models.CASCADE)
    factory_name=models.CharField(max_length=100, blank=True)
    factory_order_number = models.CharField(max_length=100, blank=True)
    order_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    production_start_date = models.DateField(null=True, blank=True)
    production_end_date = models.DateField(null=True, blank=True)
    status=models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at=models.DateTimeField(auto_now_add=True)
    
    furniture_reminder_date = models.DateField(null=True, blank=True, editable=False)
    is_furniture_reminder_sent = models.BooleanField(default=False)
    
    package_clarification_reminder_date = models.DateField(null=True, blank=True, editable=False)
    is_package_clarification_reminder_sent = models.BooleanField(default=False)
    
    def save(self, *args, **kwargs):
        from datetime import timedelta
        if self.production_start_date:
            self.furniture_reminder_date = self.production_start_date - timedelta(days=3)
        else:
            self.furniture_reminder_date = None

        if self.production_end_date:
            self.package_clarification_reminder_date = self.production_end_date
        else:
            self.package_clarification_reminder_date = None

        super().save(*args, **kwargs)

    def __str__(self):
        return f"Factory Order for {self.order}"
    
class ClientOrder(models.Model):
    
    order=models.ForeignKey(Order, on_delete=models.CASCADE)
    client=models.ForeignKey(Client, on_delete=models.PROTECT)
    client_representative = models.CharField(max_length=100, blank=True)
    client_contact = models.CharField(max_length=150, blank=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    status=models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at=models.DateTimeField(auto_now_add=True)

    payment_type = models.CharField(max_length=50, choices=PaymentType.choices, blank=True, default="")
    def __str__(self):
        return f"Client Order for {self.order}"
    
class DepositType(models.Model):
    type_name = models.CharField(max_length=100, unique=True)


    def __str__(self):
        return self.type_name
    
class DepositFactory(models.Model):
    factory_order = models.ForeignKey(FactoryOrder, on_delete=models.CASCADE)
    deposit_type = models.ForeignKey(DepositType, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    is_paid = models.BooleanField(default=False)
    payment_due_by = models.DateField(null=True, blank=True)
    is_reminder_sent = models.BooleanField(default=False)
    reminder_date = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "Factory deposit"
        verbose_name_plural = "Factory deposits"

    def save(self, *args, **kwargs):
        if self.payment_due_by:
            from django.utils import timezone
            from datetime import timedelta
            days_until_due = (self.payment_due_by - timezone.now().date()).days
            if days_until_due <= REMINDER_DAYS_BEFORE:
                self.reminder_date = timezone.now().date()
            else:
                self.reminder_date = self.payment_due_by - timedelta(days=REMINDER_DAYS_BEFORE)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Factory deposit for {self.factory_order} - {self.deposit_type}"
    
    
class DepositClient(models.Model):
    client_order = models.ForeignKey(ClientOrder, on_delete=models.CASCADE)
    deposit_type = models.ForeignKey(DepositType, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    is_paid = models.BooleanField(default=False)
    payment_due_by = models.DateField(null=True, blank=True)
    is_reminder_sent = models.BooleanField(default=False)
    reminder_date = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "Client deposit"
        verbose_name_plural = "Client deposits"
        
    def save(self, *args, **kwargs):
        if self.payment_due_by:
            from django.utils import timezone
            from datetime import timedelta
            days_until_due = (self.payment_due_by - timezone.now().date()).days
            if days_until_due <= REMINDER_DAYS_BEFORE:
                self.reminder_date = timezone.now().date()
            else:
                self.reminder_date = self.payment_due_by - timedelta(days=REMINDER_DAYS_BEFORE)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Client deposit for {self.client_order} - {self.deposit_type}"
    
class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    phone_number = models.CharField(
        max_length=20, blank=True,
        help_text="E.164 format, e.g. +37060012345 — required for password recovery via SMS."
    )

    def __str__(self):
        return f"Profile for {self.user.username}"


class RecoveryCode(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recovery_codes")
    code_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    invalidated_at = models.DateTimeField(null=True, blank=True)

    def is_valid(self):
        return self.used_at is None and self.invalidated_at is None and timezone.now() < self.expires_at

    def __str__(self):
        return f"Recovery code for {self.user.username} (expires {self.expires_at})"


class RecoveryLockout(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recovery_lockout")
    attempt_count = models.PositiveIntegerField(default=0)
    window_started_at = models.DateTimeField(null=True, blank=True)
    locked_until = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Recovery lockout state for {self.user.username}"
    
class ApiToken(models.Model):
    label = models.CharField(
        max_length=100,
        help_text="Which machine/coworker this token belongs to, e.g. 'Jonas — office PC'."
    )
    token = models.CharField(max_length=64, unique=True, editable=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets_module.token_hex(32)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.label} ({'active' if self.is_active else 'revoked'})"

class RecoverySession(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recovery_sessions")
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True, help_text="When the recovery session was completed (successfully or not).")
    result = models.CharField(max_length=10, choices=Status_recovery_session.choices, default=Status_recovery_session.ACTIVE,)
    ip_address = models.GenericIPAddressField(null=True, blank=True, help_text="IP address from which the recovery session was initiated.")

    def __str__(self):
        return (f"{self.user.username} " f"({self.started_at:%Y-%m-%d %H:%M}) " f"- {self.result}")
        
class RecoveryAttempt(models.Model):
    session = models.ForeignKey(RecoverySession, on_delete=models.CASCADE, related_name="events", null=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recovery_attempts")
    status = models.CharField(max_length=30, choices=Status_recovery.choices, default=Status_recovery.INITIATED)
    created_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    detail = models.TextField(blank=True, help_text="Error message or extra context, if any.")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} — {self.get_status_display()} @ {self.created_at:%Y-%m-%d %H:%M}"