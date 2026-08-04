import secrets
import hashlib
from unittest import result
import requests
from django.conf import settings
from datetime import timedelta
from django.utils import timezone
from .constants import (
    RECOVERY_CODE_VALID_MINUTES,
    RECOVERY_RATE_LIMIT_WINDOW_MINUTES,
    RECOVERY_RATE_LIMIT_MAX_ATTEMPTS,
    RECOVERY_LOCKOUT_HOURS,
)
from .models import (RecoveryCode, RecoveryLockout)


class RecoveryCodeLocked(Exception):
    def __init__(self, locked_until):
        self.locked_until = locked_until
        super().__init__(f"Locked until {locked_until}")


class NoPhoneNumberOnFile(Exception):
    pass


SEVEN_API_URL = "https://gateway.seven.io/api/sms"

class SmsDeliveryError(Exception):
    pass

def _send_sms(phone_number, body):
    response = requests.post(
        SEVEN_API_URL,
        headers={
            "X-Api-Key": settings.SEVEN_API_KEY,
        },
        data={
            "to": phone_number,
            "text": body,
            "from": "AG Solutions",
        },
        timeout=10,
    )

    response.raise_for_status()

    result = response.text.strip()
    
    print("Seven status:", response.status_code)
    print("Seven response:", repr(result))

    if result != "100":
        raise SmsDeliveryError(f"Seven API reported failure: {result}")

def generate_and_send_recovery_code(target_user):
    """
    Generates a fresh recovery code for target_user and 'sends' it (see
    _send_sms stub above). Enforces the rate limit before doing anything
    else — no code is created if the user is currently locked out or
    over the attempt limit.

    Raises NoPhoneNumberOnFile or RecoveryCodeLocked. Returns nothing —
    the raw code only ever exists inside _send_sms's argument.
    """
    now = timezone.now()

    profile = getattr(target_user, "profile", None)
    if not profile or not profile.phone_number:
        raise NoPhoneNumberOnFile()

    lockout, _ = RecoveryLockout.objects.get_or_create(user=target_user)

    if lockout.locked_until and now < lockout.locked_until:
        raise RecoveryCodeLocked(lockout.locked_until)

    window = timedelta(minutes=RECOVERY_RATE_LIMIT_WINDOW_MINUTES)
    if not lockout.window_started_at or now - lockout.window_started_at > window:
        lockout.window_started_at = now
        lockout.attempt_count = 0

    lockout.attempt_count += 1

    if lockout.attempt_count > RECOVERY_RATE_LIMIT_MAX_ATTEMPTS:
        lockout.locked_until = now + timedelta(hours=RECOVERY_LOCKOUT_HOURS)
        lockout.save()
        raise RecoveryCodeLocked(lockout.locked_until)

    lockout.save()

    RecoveryCode.objects.filter(
        user=target_user,
        used_at__isnull=True,
        invalidated_at__isnull=True
    ).update(invalidated_at=now)
    
    raw_code = f"{secrets.randbelow(10**8):08d}"
    code_hash = hashlib.sha256(raw_code.encode()).hexdigest()
    
    RecoveryCode.objects.create(
        user=target_user,
        code_hash=code_hash,
        expires_at=now + timedelta(minutes=RECOVERY_CODE_VALID_MINUTES),
    )
           
    _send_sms(
        profile.phone_number,
        f"AG Solutions password recovery code: {raw_code} (valid for {RECOVERY_CODE_VALID_MINUTES} minutes).",
    )
    
def verify_recovery_code(user, raw_code):
    code_hash = hashlib.sha256(raw_code.strip().encode()).hexdigest()
    candidate = (
        RecoveryCode.objects
        .filter(user=user, code_hash=code_hash)
        .order_by("-created_at")
        .first()
    )
    if not candidate or not candidate.is_valid():
        return False

    candidate.used_at = timezone.now()
    candidate.save()
    return True