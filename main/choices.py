from django.db import models

class Status(models.TextChoices):
    PENDING = "pending", "Pending"
    IN_PROGRESS = "in_progress", "In Progress"
    COMPLETED = "completed", "Completed"
    
class PaymentType(models.TextChoices):
    PAYMENT_TYPE_FULL = "visa_suma", "Visa suma"
    PAYMENT_TYPE_DEPOSIT = "avansas", "Avansas"
    PAYMENT_TYPE_AFTER_DELIVERY = "po_pristatymo", "Po pristatymo"