import secrets
import hashlib
import requests
from django.conf import settings
from django.utils.translation import gettext as _
from django.utils import translation
from datetime import date, timedelta
from django.utils import timezone
from .constants import (
    CONTRACT_NUMBER_PATTERN,
    RECOVERY_CODE_VALID_MINUTES,
    RECOVERY_RATE_LIMIT_WINDOW_MINUTES,
    RECOVERY_RATE_LIMIT_MAX_ATTEMPTS,
    RECOVERY_LOCKOUT_HOURS,
    DEPOSIT_TYPE_PRIORITY,
    SEVEN_API_URL
)
from .models import (RecoveryAttempt, RecoveryCode, RecoveryLockout, SiteSettings)
from django_celery_results.models import TaskResult

class RecoveryCodeLocked(Exception):
    def __init__(self, locked_until):
        self.locked_until = locked_until
        super().__init__(f"Locked until {locked_until}")


class NoPhoneNumberOnFile(Exception):
    pass

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


def send_keepalive_sms(phone_number):
    message = "AG Solutions — automated keepalive ping, no action needed."
    _send_sms(phone_number, message)
    return message


def check_seven_balance():
    response = requests.get(
        "https://gateway.seven.io/api/balance",
        headers={"X-API-Key": settings.SEVEN_API_KEY},
        timeout=10,
    )
    response.raise_for_status()
    return response.text.strip()


def generate_and_send_recovery_code(target_user, ip_address=None, recovery_session=None):
    if recovery_session is None:
        raise ValueError("recovery_session must be provided for recovery code generation")

    now = timezone.now()

    profile = getattr(target_user, "profile", None)
    if not profile or not profile.phone_number:
        RecoveryAttempt.objects.create(
            user=target_user, status="failed_no_phone", ip_address=ip_address, session=recovery_session
        )
        raise NoPhoneNumberOnFile()

    lockout, _created = RecoveryLockout.objects.get_or_create(user=target_user)

    if lockout.locked_until and now < lockout.locked_until:
        RecoveryAttempt.objects.create(
            user=target_user, status="failed_lockout", ip_address=ip_address, session=recovery_session,
            detail=f"Locked until {lockout.locked_until}",
        )
        raise RecoveryCodeLocked(lockout.locked_until)

    window = timedelta(minutes=RECOVERY_RATE_LIMIT_WINDOW_MINUTES)
    if not lockout.window_started_at or now - lockout.window_started_at > window:
        lockout.window_started_at = now
        lockout.attempt_count = 0

    lockout.attempt_count += 1

    if lockout.attempt_count > RECOVERY_RATE_LIMIT_MAX_ATTEMPTS:
        lockout.locked_until = now + timedelta(hours=RECOVERY_LOCKOUT_HOURS)
        lockout.save()
        RecoveryAttempt.objects.create(
            user=target_user, status="failed_lockout", ip_address=ip_address, session=recovery_session,
            detail="Rate limit exceeded — lockout just triggered",
        )
        raise RecoveryCodeLocked(lockout.locked_until)

    lockout.save()

    RecoveryCode.objects.filter(
        user=target_user, used_at__isnull=True, invalidated_at__isnull=True
    ).update(invalidated_at=now)

    raw_code = f"{secrets.randbelow(10**8):08d}"
    code_hash = hashlib.sha256(raw_code.encode()).hexdigest()

    RecoveryCode.objects.create(
        user=target_user,
        code_hash=code_hash,
        expires_at=now + timedelta(minutes=RECOVERY_CODE_VALID_MINUTES),
    )

    try:
        _send_sms(
            profile.phone_number,
            f"AG Solutions password recovery code: {raw_code} (valid for {RECOVERY_CODE_VALID_MINUTES} minutes).",
        )
    except Exception as exc:
        RecoveryAttempt.objects.create(
            user=target_user, status="failed_sms_error", ip_address=ip_address, session=recovery_session,
            detail=str(exc),
        )
        raise

    RecoveryAttempt.objects.create(
        user=target_user, status="initiated", ip_address=ip_address, session=recovery_session
    )


def verify_recovery_code(user, raw_code, ip_address=None, recovery_session=None):
    if recovery_session is None:
        raise ValueError("recovery_session must be provided for recovery code verification")

    code_hash = hashlib.sha256(raw_code.strip().encode()).hexdigest()
    candidate = (
        RecoveryCode.objects
        .filter(user=user, code_hash=code_hash)
        .order_by("-created_at")
        .first()
    )
    if not candidate or not candidate.is_valid():
        RecoveryAttempt.objects.create(
            user=user, status="failed_invalid_code", ip_address=ip_address, session=recovery_session,
        )
        return False

    candidate.used_at = timezone.now()
    candidate.save()

    RecoveryAttempt.objects.create(
        user=user, status="code_verified", ip_address=ip_address, session=recovery_session, detail="Code verified successfully",
    )
    return True

def compute_deposit_status(deposits, today):
    deposits = list(deposits)
    if not deposits:
        return {
            "token": "due",
            "paid": False,
            "label": _("no deposit info"),
            "deposit_type": None,
            "days_remaining": None,
            "overdue": False,
            "reminder_sent": False,
        }

    unpaid = [d for d in deposits if not d.is_paid]
    if not unpaid:
        return {
            "token": "paid",
            "paid": True,
            "label": _("Paid ✓"),
            "deposit_type": None,
            "days_remaining": None,
            "overdue": False,
            "reminder_sent": False,
        }

    informative_unpaid = [
        d for d in unpaid if d.amount is not None or d.payment_due_by is not None
    ]
    if not informative_unpaid:
        return {
            "token": "due",
            "paid": False,
            "label": _("no deposit info"),
            "deposit_type": None,
            "days_remaining": None,
            "overdue": False,
            "reminder_sent": False,
        }

    informative_unpaid.sort(key=lambda d: DEPOSIT_TYPE_PRIORITY.get(d.deposit_type.type_name, 99))
    active = informative_unpaid[0]
    dated_unpaid = sorted(
        (d for d in informative_unpaid if d.payment_due_by),
        key=lambda d: DEPOSIT_TYPE_PRIORITY.get(d.deposit_type.type_name, 99),
    )
    if dated_unpaid:
        active = dated_unpaid[0]

    days_remaining = None
    overdue = False
    if active.payment_due_by:
        days_remaining = (active.payment_due_by - today).days
        overdue = days_remaining < 0

    if days_remaining is None:
        label = _("%(type)s due") % {"type": active.deposit_type.type_name}
    elif overdue:
        label = _("%(type)s overdue by %(days)s days") % {
            "type": active.deposit_type.type_name, "days": abs(days_remaining)
        }
    else:
        label = _("%(type)s due in %(days)s days") % {
            "type": active.deposit_type.type_name, "days": days_remaining
        }

    return {
        "token": "overdue" if overdue else "due",
        "paid": False,
        "label": label,
        "deposit_type": active.deposit_type.type_name,
        "days_remaining": days_remaining,
        "overdue": overdue,
        "reminder_sent": active.is_reminder_sent,
    }


def compute_transport_status(transport, today):
    if not transport:
        return {
            "token": "pending",
            "label": _("Transport pending"),
            "courier": "",
            "days_remaining": None,
            "overdue": False,
            "reminder_sent": False,
        }

    courier = (transport.courier or "").strip()
    confirmed = bool(courier)

    days_remaining = None
    overdue = False
    if transport.delivery_date:
        days_remaining = (transport.delivery_date - today).days
        overdue = days_remaining < 0 and not confirmed

    if confirmed:
        token = "confirmed"
        if transport.delivery_date and days_remaining is not None and days_remaining < 0:
            label = _("Transport confirmed · overdue by %(days)s days past original date") % {
                "days": abs(days_remaining)
            }
        else:
            label = _("Transport confirmed")
    elif overdue:
        token = "overdue"
        label = _("Transport pending · overdue by %(days)s days") % {"days": abs(days_remaining)}
    elif days_remaining is not None:
        token = "pending"
        label = _("Transport pending · %(days)s days remaining") % {"days": days_remaining}
    else:
        token = "pending"
        label = _("Transport pending")

    return {
        "token": token,
        "label": label,
        "courier": courier,
        "days_remaining": days_remaining,
        "overdue": overdue,
        "reminder_sent": transport.is_reminder_sent,
    }

def compute_furniture_status(factory_order, today):
    if not factory_order or not factory_order.furniture_reminder_date:
        return None

    days_remaining = (factory_order.furniture_reminder_date - today).days
    overdue = days_remaining <= 0
    if factory_order.is_furniture_reminder_sent:
        token = "paid"
        label = _("Furniture reminder sent")
    elif overdue:
        token = "overdue"
        label = _("Furniture reminder overdue by %(days)s days") % {"days": abs(days_remaining)}
    else:
        token = "due"
        label = _("Furniture reminder in %(days)s days") % {"days": days_remaining}

    return {
        "label": label,
        "token": token,
        "due": overdue,
        "days_remaining": days_remaining,
        "reminder_sent": factory_order.is_furniture_reminder_sent,
    }


def compute_package_clarification_status(factory_order, today):
    if not factory_order or not factory_order.package_clarification_reminder_date:
        return None

    days_remaining = (factory_order.package_clarification_reminder_date - today).days
    overdue = days_remaining <= 0
    if factory_order.is_package_clarification_reminder_sent:
        token = "paid"
        label = _("Package clarification reminder sent")
    elif overdue:
        token = "overdue"
        label = _("Package clarification overdue by %(days)s days") % {"days": abs(days_remaining)}
    else:
        token = "due"
        label = _("Package clarification in %(days)s days") % {"days": days_remaining}

    return {
        "label": label,
        "token": token,
        "due": overdue,
        "days_remaining": days_remaining,
        "reminder_sent": factory_order.is_package_clarification_reminder_sent,
    }

def get_client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")

def is_order_complete(client_status, factory_status, transport_status,
                        furniture_status, package_clarification_status):
    return (
        client_status["paid"]
        and factory_status["paid"]
        and transport_status["token"] == "confirmed"
        and (furniture_status is None or furniture_status["reminder_sent"])
        and (package_clarification_status is None or package_clarification_status["reminder_sent"])
    )


def get_latest_sync_result():
    return (
        TaskResult.objects
        .filter(task_name="main.tasks.sync_sheet_task", status="SUCCESS")
        .order_by("-date_done")
        .first()
    )

def extract_contract_date(contract_number):
    match = CONTRACT_NUMBER_PATTERN.match(contract_number)
    if not match:
        return None
    year_prefix, month, day = match.groups()
    try:
        return date(2000 + int(year_prefix), int(month), int(day))
    except ValueError:
        return None

def get_due_reminders(today):
    """
    Shared logic for both reminders_due_api and check_reminders_task —
    returns a list of {"id": ..., "message": ...} for every currently-due,
    not-yet-marked-sent reminder across all orders.
    """
    from .models import Order

    with translation.override(SiteSettings.get_language()):
        due = []
        orders = Order.objects.select_related("client").prefetch_related(
            "clientorder_set__depositclient_set__deposit_type",
            "factoryorder_set__depositfactory_set__deposit_type",
            "transport",
        )

        for order in orders:
            client_order = order.clientorder_set.first()
            factory_order = order.factoryorder_set.first()
            transport = getattr(order, "transport", None)

            client_status = compute_deposit_status(
                client_order.depositclient_set.all() if client_order else [], today
            )
            factory_status = compute_deposit_status(
                factory_order.depositfactory_set.all() if factory_order else [], today
            )
            transport_status = compute_transport_status(transport, today)
            furniture_status = compute_furniture_status(factory_order, today)
            package_status = compute_package_clarification_status(factory_order, today)

            if (not client_status["paid"] and not client_status["reminder_sent"]
                    and client_status["days_remaining"] is not None and client_status["days_remaining"] <= 7):
                due.append({"id": f"client-deposit-{order.id}", "message": _("%(contract)s: Client %(label)s") % {"contract": order.contract_number, "label": client_status["label"]}})

            if (not factory_status["paid"] and not factory_status["reminder_sent"]
                    and factory_status["days_remaining"] is not None and factory_status["days_remaining"] <= 7):
                due.append({"id": f"factory-deposit-{order.id}", "message": _("%(contract)s: Factory %(label)s") % {"contract": order.contract_number, "label": factory_status["label"]}})

            if (transport_status["token"] != "confirmed" and not transport_status["reminder_sent"]
                    and transport_status["days_remaining"] is not None and transport_status["days_remaining"] <= 7):
                due.append({"id": f"transport-{order.id}", "message": _("%(contract)s: %(label)s") % {"contract": order.contract_number, "label": transport_status["label"]}})

            if furniture_status and furniture_status["due"] and not furniture_status["reminder_sent"]:
                due.append({"id": f"furniture-{factory_order.id}", "message": _("%(contract)s: %(label)s") % {"contract": order.contract_number, "label": furniture_status["label"]}})

            if package_status and package_status["due"] and not package_status["reminder_sent"]:
                due.append({"id": f"package-{factory_order.id}", "message": _("%(contract)s: %(label)s") % {"contract": order.contract_number, "label": package_status["label"]}})

        return due
