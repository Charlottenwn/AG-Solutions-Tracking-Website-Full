from django.db import models

REMINDER_DAYS_BEFORE = 7

class Client(models.Model):
    client_name = models.CharField(max_length=100)
    client_contact_number = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return self.client_name
    
class Order(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('in_progress', 'In Progress'),
    ]
    client = models.ForeignKey(Client, on_delete=models.PROTECT)
    contract_number = models.CharField(max_length=50, unique=True)
    country = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
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
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('in_progress', 'In Progress'),
    ]
    order=models.ForeignKey(Order, on_delete=models.CASCADE)
    factory_name=models.CharField(max_length=100, blank=True)
    factory_order_number = models.CharField(max_length=100, blank=True)
    order_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    production_start_date = models.DateField(null=True, blank=True)
    production_end_date = models.DateField(null=True, blank=True)
    status=models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at=models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Factory Order for {self.order}"
    
class ClientOrder(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('in_progress', 'In Progress'),
    ]
    order=models.ForeignKey(Order, on_delete=models.CASCADE)
    client=models.ForeignKey(Client, on_delete=models.PROTECT)
    client_representative = models.CharField(max_length=100, blank=True)
    client_contact = models.CharField(max_length=150, blank=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    status=models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at=models.DateTimeField(auto_now_add=True)

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