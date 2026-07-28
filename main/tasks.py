import json
import logging
from celery import shared_task
from django.core.management import call_command

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_sheet_task(self):
    try:
        raw_result = call_command("sync_sheet")
        return json.loads(raw_result) if raw_result else None
    except Exception as exc:
        logger.exception("sync_sheet_task failed")
        raise self.retry(exc=exc)