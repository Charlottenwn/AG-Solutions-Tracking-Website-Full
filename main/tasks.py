from datetime import timedelta
from django.utils import timezone
import json
import logging
import requests
from celery import shared_task
from django.core.management import call_command
from .services import get_due_reminders, check_seven_balance
from main.models import NtfySentReminder
from django.conf import settings

NTFY_RENOTIFY_INTERVAL = timedelta(hours=24)
logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_sheet_task(self):
    try:
        raw_result = call_command("sync_sheet")
        return json.loads(raw_result) if raw_result else None
    except Exception as exc:
        logger.exception("sync_sheet_task failed")
        raise self.retry(exc=exc)

def _push_ntfy(message, title="AG Solutions Reminder"):
    response = requests.post(
        f"{settings.NTFY_BASE_URL}/{settings.NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers={"Title": title, "Priority": "default"},
        auth=(settings.NTFY_USER, settings.NTFY_PASSWORD),
        timeout=10,
    )
    response.raise_for_status()


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def check_reminders_task(self):
    now = timezone.now()
    today = now.date()

    due = get_due_reminders(today)
    due_ids = {item["id"] for item in due}

    # Clean up tracking rows for reminders that are no longer due
    # (resolved, marked sent, etc.) so they start fresh if they ever
    # recur.
    NtfySentReminder.objects.exclude(reminder_id__in=due_ids).delete()

    existing = {
        row.reminder_id: row.last_sent_at
        for row in NtfySentReminder.objects.filter(reminder_id__in=due_ids)
    }

    pushed = 0
    for item in due:
        last_sent = existing.get(item["id"])
        if last_sent and (now - last_sent) < NTFY_RENOTIFY_INTERVAL:
            continue

        try:
            _push_ntfy(item["message"])
        except Exception as exc:
            logger.exception(f"ntfy push failed for {item['id']}")
            raise self.retry(exc=exc)

        row, _ = NtfySentReminder.objects.update_or_create(
            reminder_id=item["id"],
            defaults={"last_sent_at": now},
        )
        pushed += 1

    return {"pushed": pushed, "total_due": len(due)}

# COMMENTED OUT SINCE 2026-08-24 (Seven API support confirmed that inactivity doesn't change anything-
# keeping code as is for potential future use. See email for more details.
#@shared_task(bind=True, max_retries=3, default_retry_delay=3600)
#def seven_sms_keepalive_task(self):
    #try:
        #message = send_keepalive_sms(settings.KEEPALIVE_PHONE_NUMBER) 
        #logger.info("Seven.io keepalive SMS sent successfully.")
        #return {"status": "sent", "message": message}
    #except Exception as exc:
        #logger.exception("Seven.io keepalive SMS failed")
        #raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=3600)
def seven_balance_keepalive_task(self):
    try:
        balance = check_seven_balance()
        logger.info(f"Seven.io balance check succeeded (keepalive). Balance: {balance}")
        return {"balance": balance}
    except Exception as exc:
        logger.exception("Seven.io balance check (keepalive) failed")
        raise self.retry(exc=exc)
