import logging
from celery import shared_task
from django.core.management import call_command

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_sheet_task(self):
    """
    Runs the existing sync_sheet management command under Celery.
    Retries up to 3 times with a 60s delay if it raises.
    """
    try:
        call_command("sync_sheet")
    except Exception as exc:
        logger.exception("sync_sheet_task failed")
        raise self.retry(exc=exc)