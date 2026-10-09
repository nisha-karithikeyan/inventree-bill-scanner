"""Phase 2: the background extraction task, failures and retries."""

import json
from datetime import timedelta
from unittest import mock

from django.core.exceptions import ValidationError
from django.utils import timezone

import requests
from django_q.exceptions import TimeoutException
from plugin.models import PluginSetting

from bill_scanner import tasks
from bill_scanner.gemini import PermanentGeminiError, TransientGeminiError
from bill_scanner.models import Bill
from bill_scanner.tests.base import SAMPLE_REPLY, SLUG, PluginTestCase
from bill_scanner.tests.test_gemini import fake_response, gemini_body


class ExtractTaskTest(PluginTestCase):
    """tasks.extract_bill."""

    def setUp(self):
        """Every test starts with a key and three attempts."""
        super().setUp()
        self.plugin.set_setting('GEMINI_API_KEY', 'test-key')
        self.plugin.set_setting('MAX_ATTEMPTS', 3)

    def run_with(self, bill, **patch):
        """Run the task with request_extraction patched."""
        with mock.patch.object(self.plugin, 'request_extraction', **patch):
            tasks.extract_bill(bill.pk)
        bill.refresh_from_db()
        return bill

    def test_success(self):
        """Header fields and lines are stored and the bill awaits review."""
        bill = self.run_with(self.make_bill(), return_value=SAMPLE_REPLY)
        self.assertEqual(bill.status, Bill.Status.REVIEW)
        self.assertEqual(bill.attempts, 1)
        self.assertEqual(bill.supplier_name, 'Acme Components Ltd')
        self.assertEqual(bill.currency, 'USD')
        self.assertEqual(bill.extracted['lines'][0]['sku'], 'ACM-M3-10')
        lines = list(bill.lines.order_by('line_number'))
        self.assertEqual([line.line_number for line in lines], [1, 2])
        self.assertEqual(str(lines[1].unit_price), '0.120000')
        self.assertAlmostEqual(lines[1].confidence, 0.4)

    def test_re_extraction_replaces_lines(self):
        """Running again does not duplicate lines."""
        bill = self.run_with(self.make_bill(), return_value=SAMPLE_REPLY)
        bill.status = Bill.Status.PENDING
        bill.save()
        bill = self.run_with(bill, return_value=SAMPLE_REPLY)
        self.assertEqual(bill.lines.count(), 2)

    def test_transient_error_schedules_retry(self):
        """A transient error moves the bill to RETRY with a backoff."""
        before = timezone.now()
        bill = self.run_with(
            self.make_bill(), side_effect=TransientGeminiError('rate limited')
        )
        self.assertEqual(bill.status, Bill.Status.RETRY)
        self.assertEqual(bill.error, 'rate limited')
        self.assertGreaterEqual(bill.next_attempt_at, before + timedelta(seconds=29))

    def test_gives_up_after_max_attempts(self):
        """The last allowed attempt marks the bill FAILED."""
        bill = self.make_bill(attempts=2, status=Bill.Status.RETRY)
        bill = self.run_with(bill, side_effect=TransientGeminiError('still down'))
        self.assertEqual(bill.attempts, 3)
        self.assertEqual(bill.status, Bill.Status.FAILED)

    def test_permanent_error_fails_immediately(self):
        """Permanent errors are not retried."""
        bill = self.run_with(
            self.make_bill(), side_effect=PermanentGeminiError('bad key')
        )
        self.assertEqual(bill.status, Bill.Status.FAILED)
        self.assertEqual(bill.attempts, 1)

    def test_unreadable_reply_is_retried(self):
        """A reply without lines counts as a retryable failure."""
        bill = self.run_with(self.make_bill(), return_value={'lines': []})
        self.assertEqual(bill.status, Bill.Status.RETRY)
        self.assertIn('Could not read the bill', bill.error)

    def test_unexpected_error_fails(self):
        """Programming errors fail the bill instead of looping."""
        bill = self.run_with(self.make_bill(), side_effect=KeyError('oops'))
        self.assertEqual(bill.status, Bill.Status.FAILED)
        self.assertIn('Unexpected error', bill.error)

    def test_worker_time_limit_is_retried(self):
        """A task killed by django-q's time limit is retried, not left stuck.

        Regression: django-q raises TimeoutException (a SystemExit) inside the
        HTTP call; it escaped 'except Exception' and left the bill processing.
        """
        error = TimeoutException('Task exceeded maximum timeout value (90 seconds)')
        bill = self.run_with(self.make_bill(), side_effect=error)
        self.assertEqual(bill.status, Bill.Status.RETRY)
        self.assertIn('time limit', bill.error)

    def test_missing_key_fails(self):
        """Without a key the real request method fails permanently."""
        self.plugin.set_setting('GEMINI_API_KEY', '')
        bill = self.make_bill()
        tasks.extract_bill(bill.pk)
        bill.refresh_from_db()
        self.assertEqual(bill.status, Bill.Status.FAILED)
        self.assertIn('not configured', bill.error)

    def test_skips_bills_not_waiting(self):
        """Bills under review or completed are left alone."""
        bill = self.make_bill(status=Bill.Status.REVIEW)
        bill = self.run_with(bill, return_value=SAMPLE_REPLY)
        self.assertEqual(bill.attempts, 0)
        tasks.extract_bill(999999)  # Unknown ids are ignored.


class GeminiCallTest(PluginTestCase):
    """The plugin's HTTP call goes through APICallMixin with the right headers."""

    def test_default_model(self):
        """Without a model setting, the current default model is called."""
        self.plugin.set_setting('GEMINI_API_KEY', 'secret-key')
        self.assertEqual(self.plugin.get_setting('GEMINI_MODEL'), 'gemini-3.8-flash')
        reply = fake_response(200, gemini_body(json.dumps(SAMPLE_REPLY)))
        with mock.patch('requests.request', return_value=reply) as request:
            self.plugin.request_extraction(b'%PDF-1', 'application/pdf')
        self.assertIn(
            '/models/gemini-3.8-flash:generateContent', request.call_args.kwargs['url']
        )

    def test_request_shape(self):
        """URL, key header, timeout and body are correct."""
        self.plugin.set_setting('GEMINI_API_KEY', 'secret-key')
        self.plugin.set_setting('GEMINI_MODEL', 'gemini-test')
        reply = fake_response(200, gemini_body(json.dumps(SAMPLE_REPLY)))
        with mock.patch('requests.request', return_value=reply) as request:
            data = self.plugin.request_extraction(b'%PDF-1', 'application/pdf')

        self.assertEqual(data, SAMPLE_REPLY)
        method = request.call_args.args[0]
        kwargs = request.call_args.kwargs
        self.assertEqual(method, 'POST')
        self.assertEqual(
            kwargs['url'],
            'https://generativelanguage.googleapis.com/v1beta/models/'
            'gemini-test:generateContent',
        )
        self.assertEqual(kwargs['headers']['x-goog-api-key'], 'secret-key')
        self.assertNotIn('Authorization', kwargs['headers'])
        self.assertEqual(kwargs['timeout'], 120)
        body = json.loads(kwargs['data'])
        self.assertEqual(
            body['contents'][0]['parts'][0]['inline_data']['mime_type'],
            'application/pdf',
        )


class GeminiPrivacyTest(PluginTestCase):
    """The key and the bill go to Google only, and the key is never stored."""

    def setUp(self):
        """Every test has a key configured."""
        super().setUp()
        self.plugin.set_setting('GEMINI_API_KEY', 'secret-key')

    def test_key_not_in_url(self):
        """The key travels in a header, never in the URL or the body."""
        reply = fake_response(200, gemini_body(json.dumps(SAMPLE_REPLY)))
        with mock.patch('requests.request', return_value=reply) as request:
            self.plugin.request_extraction(b'%PDF-1', 'application/pdf')
        kwargs = request.call_args.kwargs
        self.assertNotIn('secret-key', kwargs['url'])
        self.assertNotIn('secret-key', kwargs['data'])

    def test_setting_refuses_other_hosts(self):
        """The host setting only accepts googleapis.com hosts."""
        with self.assertRaises(ValidationError):
            self.plugin.set_setting('GEMINI_API_URL', 'proxy.example.com/v1beta')
        self.plugin.set_setting(
            'GEMINI_API_URL', 'eu-generativelanguage.googleapis.com/v1'
        )

    def test_call_refuses_other_hosts(self):
        """A host stored before the validator existed is still refused."""
        # Write the row directly: save() would run the validator.
        self.plugin.set_setting(
            'GEMINI_API_URL', 'generativelanguage.googleapis.com/v1'
        )
        PluginSetting.objects.filter(plugin__key=SLUG, key='GEMINI_API_URL').update(
            value='proxy.example.com/v1beta'
        )
        with (
            mock.patch('requests.request') as request,
            self.assertRaises(PermanentGeminiError),
        ):
            self.plugin.request_extraction(b'%PDF-1', 'application/pdf')
        request.assert_not_called()

    def test_key_redacted_from_errors(self):
        """An error body that echoes the key is masked before it is stored."""
        reply = fake_response(400, {'error': {'message': 'bad key secret-key'}})
        with (
            mock.patch('requests.request', return_value=reply),
            self.assertRaises(PermanentGeminiError) as caught,
        ):
            self.plugin.request_extraction(b'%PDF-1', 'application/pdf')
        self.assertNotIn('secret-key', str(caught.exception))
        self.assertIn('***', str(caught.exception))

    def test_network_error_chain_dropped(self):
        """The requests error (whose request holds the key) is not chained."""
        error = requests.ConnectionError('refused secret-key')
        with (
            mock.patch('requests.request', side_effect=error),
            self.assertRaises(TransientGeminiError) as caught,
        ):
            self.plugin.request_extraction(b'%PDF-1', 'application/pdf')
        self.assertNotIn('secret-key', str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)

    def test_task_stores_no_key(self):
        """A failed extraction stores and logs the masked message only."""
        bill = self.make_bill()
        reply = fake_response(403, {'error': {'message': 'key secret-key denied'}})
        with (
            mock.patch('requests.request', return_value=reply),
            self.assertLogs('inventree', level='WARNING') as logs,
        ):
            tasks.extract_bill(bill.pk)
        bill.refresh_from_db()
        self.assertEqual(bill.status, Bill.Status.FAILED)
        self.assertNotIn('secret-key', bill.error)
        self.assertNotIn('secret-key', '\n'.join(logs.output))


class RetrySchedulerTest(PluginTestCase):
    """tasks.retry_due_bills, run every minute by ScheduleMixin."""

    def setUp(self):
        """Use three attempts."""
        super().setUp()
        self.plugin.set_setting('MAX_ATTEMPTS', 3)

    def test_requeues_only_due_bills(self):
        """Bills whose backoff expired are queued; others wait."""
        now = timezone.now()
        due = self.make_bill(status=Bill.Status.RETRY, next_attempt_at=now)
        later = self.make_bill(
            status=Bill.Status.RETRY, next_attempt_at=now + timedelta(minutes=5)
        )
        with mock.patch.object(tasks, 'queue_extraction') as queue:
            self.assertEqual(tasks.retry_due_bills(), 1)
        queue.assert_called_once()
        self.assertEqual(queue.call_args.args[0].pk, due.pk)
        later.refresh_from_db()
        self.assertEqual(later.status, Bill.Status.RETRY)

    def test_rescues_stuck_bills(self):
        """A bill stuck in PROCESSING is retried, or failed when out of attempts."""
        stuck = self.make_bill(status=Bill.Status.PROCESSING, attempts=1)
        spent = self.make_bill(status=Bill.Status.PROCESSING, attempts=3)
        old = timezone.now() - timedelta(hours=1)
        Bill.objects.filter(pk__in=[stuck.pk, spent.pk]).update(updated=old)

        with mock.patch.object(tasks, 'queue_extraction'):
            tasks.retry_due_bills()

        stuck.refresh_from_db()
        spent.refresh_from_db()
        self.assertEqual(stuck.status, Bill.Status.RETRY)
        self.assertEqual(spent.status, Bill.Status.FAILED)

    def test_queue_uses_offload_task(self):
        """Extraction is offloaded without q2 retries, with room for the HTTP call.

        Regression: the worker's default 90 s task limit was shorter than the
        120 s request timeout, so slow Gemini replies killed the task.
        """
        self.plugin.set_setting('REQUEST_TIMEOUT', 120)
        bill = self.make_bill()
        with mock.patch.object(tasks, 'offload_task') as offload:
            tasks.queue_extraction(bill)
        offload.assert_called_once_with(
            'bill_scanner.tasks.extract_bill',
            bill.pk,
            group='bill_scanner',
            retry=False,
            timeout=150,
        )

    def test_request_timeout_fits_the_worker_limit(self):
        """The request timeout cannot exceed what InvenTree lets a task run."""
        with self.assertRaises(ValidationError):
            self.plugin.set_setting('REQUEST_TIMEOUT', 300)
        self.plugin.set_setting('REQUEST_TIMEOUT', tasks.MAX_REQUEST_TIMEOUT)

    def test_backoff_doubles(self):
        """Backoff is 30s, 60s, 120s."""
        self.assertEqual(
            [tasks.retry_delay(n).seconds for n in (1, 2, 3)], [30, 60, 120]
        )

    def test_schedule_registered(self):
        """The plugin declares the retry schedule."""
        task = self.plugin.get_scheduled_tasks()['retry_bills']
        self.assertEqual(task['func'], 'bill_scanner.tasks.retry_due_bills')
        self.assertEqual(task['schedule'], 'I')
