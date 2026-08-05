import re

# /main/models.py
REMINDER_DAYS_BEFORE = 7
RECOVERY_CODE_VALID_MINUTES = 5

# /main/services.py
RECOVERY_RATE_LIMIT_WINDOW_MINUTES = 3
RECOVERY_RATE_LIMIT_MAX_ATTEMPTS = 3
RECOVERY_LOCKOUT_HOURS = 0.01

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