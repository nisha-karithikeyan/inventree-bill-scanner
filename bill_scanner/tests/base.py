"""Shared helpers for the plugin test suite."""

from __future__ import annotations

import itertools
import shutil
import tempfile
from typing import Any

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from common.models import InvenTreeSetting
from InvenTree.unit_test import InvenTreeAPITestCase
from plugin import registry

from bill_scanner.core import BillScannerPlugin

SLUG = BillScannerPlugin.SLUG
API = f'/plugin/{SLUG}/api'

PNG_BYTES = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64
PDF_BYTES = b'%PDF-1.7\n' + b'0' * 64

SAMPLE_REPLY: dict[str, Any] = {
    'supplier_name': 'Acme Components Ltd',
    'bill_number': 'INV-1001',
    'bill_date': '2026-09-30',
    'currency': 'usd',
    'lines': [
        {
            'description': 'M3 x 10 hex screw',
            'sku': 'ACM-M3-10',
            'quantity': 100,
            'unit_price': 0.05,
            'confidence': 0.95,
        },
        {
            'description': 'Red LED 5mm',
            'sku': '',
            'quantity': '25',
            'unit_price': '0,12',
            'confidence': 0.4,
        },
    ],
}


_unique = itertools.count()


def png_upload(name: str = 'bill.png', content: bytes = PNG_BYTES):
    """A small upload whose bytes look like a PNG."""
    return SimpleUploadedFile(name, content, content_type='image/png')


class PluginTestCase(InvenTreeAPITestCase):
    """API test case with the bill scanner plugin active and isolated media."""

    roles = [
        'purchase_order.view',
        'purchase_order.add',
        'purchase_order.change',
        'purchase_order.delete',
        'stock.add',
    ]

    @classmethod
    def setUpClass(cls):
        """Write uploads to a throwaway media folder."""
        cls._media = tempfile.mkdtemp(prefix='bill-scanner-test-')
        cls._media_override = override_settings(MEDIA_ROOT=cls._media)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        """Remove the throwaway media folder."""
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        """Activate the plugin and the plugin features it relies on."""
        super().setUpTestData()
        for key in (
            'ENABLE_PLUGINS_APP',
            'ENABLE_PLUGINS_URL',
            'ENABLE_PLUGINS_INTERFACE',
            'ENABLE_PLUGINS_SCHEDULE',
        ):
            InvenTreeSetting.set_setting(key, True, change_user=None)
        registry.set_plugin_state(SLUG, True)

    @property
    def plugin(self) -> BillScannerPlugin:
        """The active plugin instance."""
        plugin = registry.get_plugin(SLUG)
        assert plugin is not None, 'bill-scanner plugin is not active'
        return plugin

    def make_bill(self, **fields):
        """Create a bill row with a stored PNG file."""
        from bill_scanner.models import Bill, sha256_of

        upload = png_upload(content=PNG_BYTES + str(next(_unique)).encode())
        bill = Bill(
            file_name=upload.name,
            content_type='image/png',
            file_hash=fields.pop('file_hash', None) or sha256_of(upload),
            created_by=self.user,
            **fields,
        )
        bill.file.save(upload.name, upload, save=False)
        bill.save()
        return bill
