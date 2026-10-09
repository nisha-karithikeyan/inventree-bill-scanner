"""Background tasks, run by InvenTree's django-q2 worker."""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

import structlog
from django_q.exceptions import TimeoutException
from InvenTree.exceptions import log_error
from InvenTree.tasks import offload_task
from plugin import registry

from .extraction import ExtractedBill, ExtractionError, parse_extraction
from .gemini import MAX_REQUEST_TIMEOUT, TASK_TIMEOUT_MARGIN, GeminiError
from .matching import match_bill
from .models import Bill, BillLine

logger = structlog.get_logger('inventree')

SLUG = 'bill-scanner'
TASK_GROUP = 'bill_scanner'
RETRY_BASE_SECONDS = 30
STUCK_AFTER = timedelta(minutes=15)


def get_plugin():
    """Return the active plugin instance, or None if it is disabled."""
    return registry.get_plugin(SLUG)


def retry_delay(attempt: int) -> timedelta:
    """Exponential backoff: 30s, 60s, 120s, ..."""
    return timedelta(seconds=RETRY_BASE_SECONDS * 2 ** max(attempt - 1, 0))


def queue_extraction(bill: Bill) -> None:
    """Hand a bill to the background worker.

    django-q2 retries are switched off: this plugin tracks attempts itself,
    so a failure never triggers a second, uncounted redelivery. The task gets
    enough time for the whole HTTP call; InvenTree's default limit is 90 s.
    """
    plugin = get_plugin()
    request_timeout = int((plugin and plugin.get_setting('REQUEST_TIMEOUT')) or 120)
    request_timeout = min(request_timeout, MAX_REQUEST_TIMEOUT)
    offload_task(
        'bill_scanner.tasks.extract_bill',
        bill.pk,
        group=TASK_GROUP,
        retry=False,
        timeout=request_timeout + TASK_TIMEOUT_MARGIN,
    )


def _claim(bill_id: int) -> Bill | None:
    """Move a waiting bill to PROCESSING, so only one worker handles it."""
    with transaction.atomic():
        bill = Bill.objects.select_for_update().filter(pk=bill_id).first()
        if bill is None or bill.status not in (Bill.Status.PENDING, Bill.Status.RETRY):
            return None
        bill.status = Bill.Status.PROCESSING
        bill.attempts += 1
        bill.next_attempt_at = None
        bill.save(update_fields=['status', 'attempts', 'next_attempt_at', 'updated'])
        return bill


def _fail(bill: Bill, message: str, retryable: bool, max_attempts: int) -> None:
    if retryable and bill.attempts < max_attempts:
        bill.status = Bill.Status.RETRY
        bill.next_attempt_at = timezone.now() + retry_delay(bill.attempts)
    else:
        bill.status = Bill.Status.FAILED
    bill.error = message
    bill.save(update_fields=['status', 'next_attempt_at', 'error', 'updated'])
    logger.warning('Bill %s extraction failed: %s', bill.pk, message)


def read_file(bill: Bill) -> bytes:
    """Read the stored bill file."""
    with bill.file.open('rb') as handle:
        return handle.read()


@transaction.atomic
def save_extraction(bill: Bill, extracted: ExtractedBill) -> None:
    """Store the parsed result and replace any previous lines."""
    bill.extracted = extracted.to_json()
    bill.supplier_name = extracted.supplier_name
    bill.bill_number = extracted.bill_number
    bill.bill_date = extracted.bill_date
    bill.currency = extracted.currency
    bill.error = ''
    bill.status = Bill.Status.REVIEW
    bill.save()

    bill.lines.all().delete()
    BillLine.objects.bulk_create(
        BillLine(
            bill=bill,
            line_number=index,
            description=line.description,
            sku=line.sku,
            quantity=line.quantity,
            unit_price=line.unit_price,
            confidence=line.confidence,
        )
        for index, line in enumerate(extracted.lines, start=1)
    )


def extract_bill(bill_id: int) -> None:
    """Send one bill to Gemini and store the structured result."""
    plugin = get_plugin()
    if plugin is None:
        logger.warning('Bill scanner plugin is not active; skipping bill %s', bill_id)
        return

    bill = _claim(bill_id)
    if bill is None:
        return

    max_attempts = int(plugin.get_setting('MAX_ATTEMPTS') or 1)
    try:
        # No local holds the file bytes: error reporters that capture stack
        # locals (such as Sentry) must never see the bill.
        raw = plugin.request_extraction(read_file(bill), bill.content_type)
        extracted = parse_extraction(raw)
    except GeminiError as exc:
        _fail(bill, str(exc), exc.retryable, max_attempts)
        return
    except ExtractionError as exc:
        _fail(bill, f'Could not read the bill: {exc}', True, max_attempts)
        return
    except TimeoutException:
        # django-q's time limit raises a SystemExit subclass, which the
        # 'except Exception' below would miss, leaving the bill processing.
        _fail(
            bill,
            'Gemini did not answer within the worker time limit',
            True,
            max_attempts,
        )
        return
    except Exception as exc:
        log_error('bill_scanner.extract_bill', plugin=SLUG)
        _fail(bill, f'Unexpected error: {exc}', False, max_attempts)
        return

    save_extraction(bill, extracted)
    match_bill(bill, min_name_score=int(plugin.get_setting('MATCH_MIN_SCORE') or 70))


def retry_due_bills() -> int:
    """Requeue bills whose backoff has expired, and rescue stuck ones.

    Runs every minute through the plugin's ScheduleMixin entry.
    """
    plugin = get_plugin()
    if plugin is None:
        return 0
    max_attempts = int(plugin.get_setting('MAX_ATTEMPTS') or 1)

    now = timezone.now()
    stuck = Bill.objects.filter(
        status=Bill.Status.PROCESSING, updated__lt=now - STUCK_AFTER
    )
    for bill in stuck:
        _fail(bill, 'Extraction did not finish in time', True, max_attempts)

    due = list(Bill.objects.filter(status=Bill.Status.RETRY, next_attempt_at__lte=now))
    for bill in due:
        queue_extraction(bill)
    return len(due)
