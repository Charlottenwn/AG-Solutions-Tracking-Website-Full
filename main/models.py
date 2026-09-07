from django.utils import timezone
from django.db import models
from django.conf import settings
from .choices import Status, PaymentType
from .constants import REMINDER_DAYS_BEFORE, compute_reminder_date

class Status_recovery(models.TextChoices):
    INITIATED = "initiated", "Initiated"
    CODE_VERIFIED = "code_verified", "Code verified"
    PASSWORD_RESET = "password_reset", "Password reset completed"
    FAILED_LOCKOUT = "failed_lockout", "Failed — locked out"
    FAILED_NO_PHONE = "failed_no_phone", "Failed — no phone on file"
    FAILED_INVALID_CODE = "failed_invalid_code", "Failed — invalid/expired code"
    FAILED_SMS_ERROR = "failed_sms_error", "Failed — SMS send error"

class Status_recovery_session(models.TextChoices):
    ACTIVE = "active", "Active"
    SUCCESS = "success", "Success"
    FAILED = "failed", "Failed"

class Client(models.Model):
    client_name = models.CharField(max_length=100)
    client_contact_number = models.CharField(max_length=20, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["client_name"]
            ),
        ]

    def __str__(self):
        return self.client_name

class Order(models.Model):
    client = models.ForeignKey(Client, on_delete=models.PROTECT)
    contract_number = models.CharField(max_length=50, unique=True)
    country = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["-created_at"]),
        ]

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
        indexes = [
            models.Index(
                fields=["reminder_date"],
                name="transport_unsent_reminder_idx",
                condition=models.Q(is_reminder_sent=False),
            ),
        ]

    def save(self, *args, **kwargs):
        self.reminder_date = compute_reminder_date(self.delivery_date)
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
    
    class Meta:
        indexes = [
            models.Index(
                fields=["furniture_reminder_date"],
                name="fo_furniture_unsent_idx",
                condition=models.Q(is_furniture_reminder_sent=False),
            ),
            models.Index(
                fields=["package_clarification_reminder_date"],
                name="fo_package_unsent_idx",
                condition=models.Q(is_package_clarification_reminder_sent=False),
            ),
        ]
        
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
        indexes = [
            models.Index(
                fields=["reminder_date"],
                name="depositfactory_unsent_idx",
                condition=models.Q(is_reminder_sent=False),
            ),
        ]

    def save(self, *args, **kwargs):
        self.reminder_date = compute_reminder_date(self.payment_due_by)
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
        indexes = [
            models.Index(
                fields=["reminder_date"],
                name="depositclient_unsent_idx",
                condition=models.Q(is_reminder_sent=False),
            ),
        ]

    def save(self, *args, **kwargs):
        self.reminder_date = compute_reminder_date(self.payment_due_by)
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

    class Meta:
        indexes = [
            models.Index(
                fields=["user"],
                name="recoverycode_active_idx",
                condition=models.Q(invalidated_at__isnull=True, used_at__isnull=True),
            ),
        ]

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

class RecoverySession(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recovery_sessions")
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True, help_text="When the recovery session was completed (successfully or not).")
    result = models.CharField(max_length=10, choices=Status_recovery_session.choices, default=Status_recovery_session.ACTIVE,)
    ip_address = models.GenericIPAddressField(null=True, blank=True, help_text="IP address from which the recovery session was initiated.")

    class Meta:
        indexes = [
            models.Index(
                fields=["user", "-started_at"]
            ),
        ]

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
        indexes = [
            models.Index(
                fields=["session", "created_at"]
            ),
        ]

    def __str__(self):
        return f"{self.user.username} — {self.get_status_display()} @ {self.created_at:%Y-%m-%d %H:%M}"

class NtfySentReminder(models.Model):
    reminder_id = models.CharField(max_length=100, unique=True)
    last_sent_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.reminder_id} — last sent {self.last_sent_at:%Y-%m-%d %H:%M}"

class SiteSettings(models.Model):
    language = models.CharField(
        max_length=5,
        choices=[("en", "English"), ("lt", "Lietuvių")],
        default="en",
    )

    class Meta:
        verbose_name = "Site settings"
        verbose_name_plural = "Site settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_language(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj.language
