import re
from datetime import timedelta
from django.utils import timezone

# /main/models.py
REMINDER_DAYS_BEFORE = 7
RECOVERY_CODE_VALID_MINUTES = 5

# /main/services.py
RECOVERY_RATE_LIMIT_WINDOW_MINUTES = 3
RECOVERY_RATE_LIMIT_MAX_ATTEMPTS = 3
RECOVERY_LOCKOUT_HOURS = 1

# /main/views.py
DEPOSIT_TYPE_PRIORITY = {"Deposit": 0, "Final Payment": 1, "Full Payment": 0}
RESET_TOKEN_SALT = "password-recovery"
RESET_TOKEN_MAX_AGE_SECONDS = 600 # 5 minutes
CONTRACT_NUMBER_PATTERN = re.compile(r"^(\d{2})[A-Z]{2} (\d{2})-(\d{2})/")

# /main/management/commands/sync_sheet.py
SHEET_TAB_NAME = "Sheet1"
HEADER_ROW = 6

DEPOSIT_TYPE_DEPOSIT = "Deposit"
DEPOSIT_TYPE_FINAL = "Final Payment"
DEPOSIT_TYPE_FULL = "Full Payment"

# /main/services.py
SEVEN_API_URL = "https://gateway.seven.io/api/sms"

# /main/models.py
def compute_reminder_date(due_date, days_before=REMINDER_DAYS_BEFORE, today=None):
    """
    Shared by Transport, DepositFactory, DepositClient.
    If due_date is within `days_before` days (or already past), the
    reminder date is "today" so it fires immediately. Otherwise it's
    `days_before` days ahead of the due date. Returns None if due_date
    is falsy.
    """
    if not due_date:
        return None
    today = today or timezone.now().date()
    days_until_due = (due_date - today).days
    if days_until_due <= days_before:
        return today
    return due_date - timedelta(days=days_before)
