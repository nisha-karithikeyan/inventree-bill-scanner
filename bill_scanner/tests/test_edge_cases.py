"""Edge cases across phases: validation branches, settings and model helpers."""

from decimal import Decimal
from unittest import mock

from django.core.exceptions import ValidationError as DjangoValidationError

from common.models import InvenTreeSetting
from company.models import Company

from bill_scanner import tasks
from bill_scanner.matching import PartMatcher
from bill_scanner.models import Bill, BillAuditLog, BillLine
from bill_scanner.services import ConfirmError, confirm_bill, find_duplicate
from bill_scanner.tests.base import API
from bill_scanner.tests.test_confirm import ConfirmTestBase


class HeaderValidationTest(ConfirmTestBase):
    """Bill header PATCH validation."""

    def test_supplier_must_be_a_supplier(self):
        """Customers cannot be chosen as the bill's supplier."""
        customer = Company.objects.create(
            name='Shop', is_supplier=False, is_customer=True
        )
        self.patch(
            f'{API}/bills/{self.bill.pk}/', {'supplier': customer.pk}, expected_code=400
        )

    def test_currency_code(self):
        """Currency must be three letters; it is upper-cased."""
        url = f'{API}/bills/{self.bill.pk}/'
        self.patch(url, {'currency': 'dollars'}, expected_code=400)
        self.patch(url, {'currency': '12A'}, expected_code=400)
        response = self.patch(url, {'currency': 'gbp'}, expected_code=200)
        self.assertEqual(response.data['currency'], 'GBP')

    def test_clearing_supplier(self):
        """A supplier cleared by the user stays cleared and lines lose it."""
        response = self.patch(f'{API}/bills/{self.bill.pk}/', {'supplier': None})
        self.assertIsNone(response.data['supplier'])
        self.assertEqual(response.data['supplier_confidence'], 0.0)
        line = self.bill.lines.get(line_number=1)
        self.assertIsNone(line.supplier_part)


class ConfirmEdgeTest(ConfirmTestBase):
    """Less common confirm paths."""

    def test_responsible_owner_when_required(self):
        """If orders need a responsible owner, the confirming user is used."""
        InvenTreeSetting.set_setting('PURCHASEORDER_REQUIRE_RESPONSIBLE', True, None)
        self.confirm()
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.purchase_order.responsible.owner, self.user)

    def test_inventree_validation_error_is_reported(self):
        """InvenTree validation errors become a 400 with the message."""
        with mock.patch(
            'order.models.PurchaseOrder.receive_line_items',
            side_effect=DjangoValidationError('Line items invalid'),
        ):
            response = self.confirm(expected_code=400)
        self.assertIn('Line items invalid', response.data['detail'])

    def test_service_rejects_unknown_bill(self):
        """The service itself refuses unknown ids."""
        with self.assertRaises(ConfirmError):
            confirm_bill(999999, self.user)

    def test_no_duplicate_check_without_supplier(self):
        """Without supplier there is nothing to compare."""
        self.bill.supplier = None
        self.assertIsNone(find_duplicate(self.bill))


class DisabledPluginTest(ConfirmTestBase):
    """Background tasks do nothing while the plugin is disabled."""

    def test_tasks_skip(self):
        """extract_bill and retry_due_bills return early."""
        bill = self.make_bill()
        with mock.patch.object(tasks, 'get_plugin', return_value=None):
            tasks.extract_bill(bill.pk)
            self.assertEqual(tasks.retry_due_bills(), 0)
        bill.refresh_from_db()
        self.assertEqual(bill.status, Bill.Status.PENDING)
        self.assertEqual(bill.attempts, 0)


class ModelHelperTest(ConfirmTestBase):
    """Model permissions hook and string forms."""

    def test_check_user_permission(self):
        """InvenTree's permission hook maps to the purchase order role."""
        self.assertTrue(Bill.check_user_permission(self.user, 'view'))
        self.clearRoles()
        self.assertFalse(BillLine.check_user_permission(self.user, 'view'))

    def test_str(self):
        """Readable names for admin and logs."""
        line = self.bill.lines.get(line_number=1)
        self.assertEqual(str(line), f'{self.bill.pk}:1 Screw')
        entry = BillAuditLog.objects.create(
            bill_id=self.bill.pk,
            bill_label=str(self.bill),
            user=self.user,
            action='edited',
        )
        self.assertIn('edited Acme - INV-1001', str(entry))
        self.assertEqual(str(Bill(file_name='x.pdf')), 'Unknown supplier - x.pdf')

    def test_empty_code_is_ignored(self):
        """A blank code never matches."""
        self.assertIsNone(PartMatcher(None).match_code(' - ', 1.0))
        self.assertEqual(self.bill.lines.get(line_number=2).quantity, Decimal('2.5'))
