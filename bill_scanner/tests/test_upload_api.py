"""Phase 2: uploading bills through the REST API."""

from unittest import mock

from bill_scanner.models import Bill
from bill_scanner.tests.base import (
    API,
    PDF_BYTES,
    SAMPLE_REPLY,
    PluginTestCase,
    png_upload,
)


class UploadApiTest(PluginTestCase):
    """POST /plugin/bill-scanner/api/bills/."""

    def upload(self, upload):
        """Post a multipart upload and run on-commit hooks (the task queue)."""
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                f'{API}/bills/', {'file': upload}, format='multipart'
            )

    def test_upload_runs_extraction(self):
        """A valid upload is stored, extracted and ready for review."""
        self.plugin.set_setting('GEMINI_API_KEY', 'k')
        with mock.patch.object(
            self.plugin, 'request_extraction', return_value=SAMPLE_REPLY
        ) as call:
            response = self.upload(png_upload())

        self.assertEqual(response.status_code, 201, response.content)
        call.assert_called_once()
        self.assertEqual(call.call_args.args[1], 'image/png')

        bill = Bill.objects.get(pk=response.data['pk'])
        self.assertEqual(bill.status, Bill.Status.REVIEW)
        self.assertEqual(bill.bill_number, 'INV-1001')
        self.assertEqual(bill.lines.count(), 2)
        self.assertEqual(bill.created_by, self.user)
        self.assertEqual(len(bill.file_hash), 64)

    def test_pdf_type_comes_from_bytes(self):
        """The stored type is sniffed, not taken from the client."""
        with mock.patch.object(
            self.plugin, 'request_extraction', return_value=SAMPLE_REPLY
        ):
            response = self.upload(png_upload('bill.jpg', PDF_BYTES))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['content_type'], 'application/pdf')

    def test_rejects_unsupported_file(self):
        """Non-image, non-PDF content is refused."""
        response = self.upload(png_upload('evil.png', b'MZ\x90\x00' * 10))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Bill.objects.count(), 0)

    def test_rejects_empty_and_large_files(self):
        """Empty files and files over the size limit are refused."""
        response = self.upload(png_upload('empty.png', b''))
        self.assertEqual(response.status_code, 400)

        self.plugin.set_setting('MAX_UPLOAD_MB', 1)
        big = b'%PDF-' + b'0' * (1024 * 1024 + 1)
        response = self.upload(png_upload('big.pdf', big))
        self.assertEqual(response.status_code, 400)
        self.assertIn('1 MB', str(response.data))

    def test_requires_purchase_order_role(self):
        """Users without the purchase order role cannot upload or list."""
        self.clearRoles()
        response = self.upload(png_upload())
        self.assertEqual(response.status_code, 403)
        self.get(f'{API}/bills/', expected_code=403)

    def test_requires_login(self):
        """Anonymous requests are rejected."""
        self.logout()
        response = self.client.get(f'{API}/bills/')
        self.assertIn(response.status_code, (302, 401, 403))


class BillApiTest(PluginTestCase):
    """List, detail, delete and re-extract."""

    def test_list_and_filter(self):
        """Bills are listed and can be filtered by status."""
        self.make_bill(status=Bill.Status.REVIEW)
        self.make_bill(status=Bill.Status.FAILED)
        response = self.get(f'{API}/bills/', expected_code=200)
        self.assertEqual(len(response.data), 2)
        response = self.get(f'{API}/bills/?status=failed', expected_code=200)
        self.assertEqual([b['status'] for b in response.data], ['failed'])

    def test_detail(self):
        """The detail view includes a file URL and status label."""
        bill = self.make_bill(status=Bill.Status.REVIEW)
        response = self.get(f'{API}/bills/{bill.pk}/', expected_code=200)
        self.assertTrue(response.data['file_url'].startswith('/media/bill_scanner/'))
        self.assertEqual(response.data['status_label'], 'Ready for review')

    def test_delete(self):
        """Unreceived bills can be deleted; received ones cannot."""
        bill = self.make_bill(status=Bill.Status.REVIEW)
        self.delete(f'{API}/bills/{bill.pk}/', expected_code=204)
        self.assertFalse(Bill.objects.filter(pk=bill.pk).exists())

        done = self.make_bill(status=Bill.Status.COMPLETED)
        self.delete(f'{API}/bills/{done.pk}/', expected_code=400)

    def test_re_extract_failed_bill(self):
        """A failed bill can be queued again with a fresh attempt counter."""
        bill = self.make_bill(status=Bill.Status.FAILED, attempts=3, error='boom')
        self.plugin.set_setting('GEMINI_API_KEY', 'k')
        with (
            mock.patch.object(
                self.plugin, 'request_extraction', return_value=SAMPLE_REPLY
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.post(f'{API}/bills/{bill.pk}/extract/', expected_code=202)
        bill.refresh_from_db()
        self.assertEqual(bill.status, Bill.Status.REVIEW)
        self.assertEqual(bill.attempts, 1)
        self.assertEqual(bill.error, '')

    def test_re_extract_refused_while_processing(self):
        """Bills already in the queue are not queued twice."""
        bill = self.make_bill(status=Bill.Status.PROCESSING)
        self.post(f'{API}/bills/{bill.pk}/extract/', expected_code=400)
