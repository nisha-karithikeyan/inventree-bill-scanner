"""Phase 5: creating the purchase order, receiving stock, duplicates and audit."""

from decimal import Decimal
from unittest import mock

from django.db import IntegrityError, transaction

from company.models import Company, SupplierPart
from order.models import PurchaseOrder
from order.status_codes import PurchaseOrderStatus
from part.models import Part
from stock.models import StockItem, StockLocation

from bill_scanner.models import Bill, BillAuditLog, normalize_bill_number
from bill_scanner.services import find_duplicate
from bill_scanner.tests.base import API, PNG_BYTES, PluginTestCase, png_upload

Action = BillAuditLog.Action


class ConfirmTestBase(PluginTestCase):
    """A supplier, parts and a reviewed bill ready to receive."""

    @classmethod
    def setUpTestData(cls):
        """Catalogue and a stock location."""
        super().setUpTestData()
        cls.acme = Company.objects.create(name='Acme', is_supplier=True, currency='EUR')
        cls.screw = Part.objects.create(name='Screw', purchaseable=True)
        cls.cable = Part.objects.create(name='Cable', purchaseable=True, IPN='CBL')
        cls.led = Part.objects.create(name='LED', purchaseable=True)
        cls.acme_screw = SupplierPart.objects.create(
            part=cls.screw, supplier=cls.acme, SKU='A-SCREW'
        )
        cls.shelf = StockLocation.objects.create(name='Shelf A')

    def setUp(self):
        """Three lines: matched, needs a new supplier part, and skipped."""
        super().setUp()
        self.bill = self.reviewed_bill('INV-1001')

    def reviewed_bill(self, number: str) -> Bill:
        """A bill under review with three lines."""
        bill = self.make_bill(
            status=Bill.Status.REVIEW,
            supplier=self.acme,
            supplier_name='Acme',
            bill_number=number,
            currency='USD',
        )
        bill.lines.create(
            line_number=1,
            description='Screw',
            sku='A-SCREW',
            quantity=Decimal(100),
            unit_price=Decimal('0.05'),
            part=self.screw,
            supplier_part=self.acme_screw,
            match_method='supplier_sku',
            match_confidence=1,
        )
        bill.lines.create(
            line_number=2,
            description='Cable 2.5m',
            quantity=Decimal('2.5'),
            unit_price=Decimal('3.20'),
            part=self.cable,
            match_method='manual',
            match_confidence=1,
        )
        bill.lines.create(
            line_number=3,
            description='Delivery fee',
            quantity=Decimal(1),
            unit_price=Decimal(10),
            skip=True,
        )
        return bill

    def confirm(self, bill=None, expected_code=200, **data):
        """POST the confirm endpoint."""
        bill = bill or self.bill
        data.setdefault('location', self.shelf.pk)
        return self.post(
            f'{API}/bills/{bill.pk}/confirm/',
            data,
            format='json',
            expected_code=expected_code,
        )


class ConfirmTest(ConfirmTestBase):
    """The happy path."""

    def test_creates_received_purchase_order(self):
        """One order, placed and fully received, with stock on the shelf."""
        response = self.confirm()
        self.assertEqual(response.data['status'], 'completed')

        self.bill.refresh_from_db()
        order = self.bill.purchase_order
        self.assertIsNotNone(order)
        self.assertEqual(order.supplier, self.acme)
        self.assertEqual(order.supplier_reference, 'INV-1001')
        self.assertEqual(order.created_by, self.user)
        self.assertEqual(order.status, PurchaseOrderStatus.COMPLETE.value)
        self.assertEqual(self.bill.bill_key, 'INV1001')

        lines = list(order.lines.order_by('reference'))
        self.assertEqual(len(lines), 2)  # The skipped fee is not ordered.
        self.assertEqual(lines[0].part, self.acme_screw)
        self.assertEqual(lines[0].purchase_price.amount, Decimal('0.05'))
        self.assertEqual(str(lines[0].purchase_price.currency), 'USD')
        self.assertTrue(all(line.received == line.quantity for line in lines))

        items = StockItem.objects.filter(purchase_order=order)
        self.assertEqual(items.count(), 2)
        self.assertTrue(all(item.location == self.shelf for item in items))
        self.assertEqual(
            sorted(item.quantity for item in items), [Decimal('2.5'), Decimal(100)]
        )

    def test_creates_missing_supplier_part(self):
        """A part without a supplier part for this supplier gets one."""
        self.confirm()
        created = SupplierPart.objects.get(supplier=self.acme, part=self.cable)
        self.assertEqual(created.SKU, 'BILL-CBL')

    def test_reuses_supplier_part_by_sku(self):
        """An existing supplier part with the printed SKU is reused."""
        existing = SupplierPart.objects.create(
            part=self.led, supplier=self.acme, SKU='L-1'
        )
        line = self.bill.lines.get(line_number=2)
        line.part, line.sku = self.led, 'l-1'
        line.save()
        self.confirm()
        self.bill.refresh_from_db()
        self.assertTrue(self.bill.purchase_order.lines.filter(part=existing).exists())

    def test_currency_falls_back_to_supplier(self):
        """Without a bill currency, the supplier's currency is used."""
        Bill.objects.filter(pk=self.bill.pk).update(currency='')
        self.confirm()
        self.bill.refresh_from_db()
        line = self.bill.purchase_order.lines.first()
        self.assertEqual(str(line.purchase_price.currency), 'EUR')

    def test_line_without_price(self):
        """A line without a price is ordered without a purchase price."""
        self.bill.lines.filter(line_number=2).update(unit_price=None)
        self.confirm()
        self.bill.refresh_from_db()
        line = self.bill.purchase_order.lines.get(part__part=self.cable)
        self.assertIsNone(line.purchase_price)

    def test_location_is_optional(self):
        """Without a location, stock uses InvenTree's fallback (none here)."""
        self.confirm(location=None)
        self.bill.refresh_from_db()
        items = StockItem.objects.filter(purchase_order=self.bill.purchase_order)
        self.assertEqual(items.count(), 2)

    def test_audit_entry(self):
        """The confirmation records who received what."""
        self.confirm()
        entry = BillAuditLog.objects.get(bill_id=self.bill.pk, action=Action.CONFIRMED)
        self.assertEqual(entry.user, self.user)
        details = entry.details
        self.assertEqual(details['bill_number'], 'INV-1001')
        self.assertEqual(details['location'], self.shelf.pk)
        self.assertEqual(len(details['stock_items']), 2)
        self.assertEqual(details['skipped'], [3])
        self.assertEqual(
            [
                (line['line'], line['part'], line['quantity'])
                for line in details['lines']
            ],
            [(1, self.screw.pk, '100.00000'), (2, self.cable.pk, '2.50000')],
        )

    def test_received_bill_is_frozen(self):
        """After receiving, the bill cannot be edited, deleted or received again."""
        self.confirm()
        self.patch(
            f'{API}/bills/{self.bill.pk}/', {'bill_number': 'x'}, expected_code=400
        )
        self.delete(f'{API}/bills/{self.bill.pk}/', expected_code=400)
        self.confirm(expected_code=400)
        self.assertEqual(PurchaseOrder.objects.count(), 1)


class ConfirmValidationTest(ConfirmTestBase):
    """Bills that are not ready are refused with a reason."""

    def assert_refused(self, message: str):
        """Confirm fails with a 400 and nothing is created."""
        response = self.confirm(expected_code=400)
        self.assertIn(message, response.data['detail'])
        self.assertEqual(PurchaseOrder.objects.count(), 0)
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.Status.REVIEW)

    def test_needs_supplier(self):
        """A supplier is required."""
        Bill.objects.filter(pk=self.bill.pk).update(supplier=None)
        self.assert_refused('supplier')

    def test_needs_bill_number(self):
        """A bill number is required (it is the duplicate key)."""
        Bill.objects.filter(pk=self.bill.pk).update(bill_number=' ')
        self.assert_refused('bill number')

    def test_needs_parts(self):
        """Every active line needs a part."""
        self.bill.lines.filter(line_number=2).update(part=None)
        self.assert_refused('Lines without a part: 2')

    def test_needs_active_lines(self):
        """At least one line must be received."""
        self.bill.lines.update(skip=True)
        self.assert_refused('no lines')

    def test_needs_review_status(self):
        """Bills still being read cannot be received."""
        Bill.objects.filter(pk=self.bill.pk).update(status=Bill.Status.PROCESSING)
        response = self.confirm(expected_code=400)
        self.assertIn('ready for review', response.data['detail'])

    def test_bad_location(self):
        """An unknown location is a validation error."""
        self.confirm(location=999999, expected_code=400)

    def test_unknown_bill(self):
        """Unknown bills are 404."""
        self.post(f'{API}/bills/999999/confirm/', {}, expected_code=404)

    def test_failure_rolls_everything_back(self):
        """If receiving fails, no order, supplier part or stock is left behind."""
        with mock.patch(
            'order.models.PurchaseOrder.receive_line_items',
            side_effect=RuntimeError('disk full'),
        ):
            with self.assertRaises(RuntimeError):
                self.confirm()
        self.assertEqual(PurchaseOrder.objects.count(), 0)
        self.assertFalse(SupplierPart.objects.filter(part=self.cable).exists())
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.Status.REVIEW)


class ConfirmPermissionTest(ConfirmTestBase):
    """Receiving needs purchase order add and stock add."""

    def test_needs_stock_add(self):
        """Without stock.add the request is refused."""
        self.clearRoles()
        for perm in ('view', 'add', 'change'):
            self.assignRole(f'purchase_order.{perm}')
        self.confirm(expected_code=403)

    def test_needs_purchase_order_add(self):
        """Without purchase_order.add the request is refused."""
        self.clearRoles()
        self.assignRole('purchase_order.view')
        self.assignRole('stock.add')
        self.confirm(expected_code=403)
        self.assertEqual(PurchaseOrder.objects.count(), 0)


class DuplicateTest(ConfirmTestBase):
    """The same bill is never received twice."""

    def test_normalize_bill_number(self):
        """Spacing, dashes and case do not matter."""
        self.assertEqual(normalize_bill_number(' inv-1001 '), 'INV1001')
        self.assertEqual(normalize_bill_number('INV 1001'), 'INV1001')

    def test_same_supplier_and_number(self):
        """A second bill with the same number (formatted differently) is refused."""
        self.confirm()
        second = self.reviewed_bill('inv 1001')
        response = self.confirm(second, expected_code=409)
        self.assertEqual(response.data['duplicate_of']['bill'], self.bill.pk)
        self.assertEqual(PurchaseOrder.objects.count(), 1)

    def test_other_supplier_same_number_is_fine(self):
        """Bill numbers only clash within one supplier."""
        self.confirm()
        other = Company.objects.create(name='Other', is_supplier=True)
        second = self.reviewed_bill('INV-1001')
        Bill.objects.filter(pk=second.pk).update(supplier=other)
        second.lines.filter(line_number=1).update(supplier_part=None)
        self.confirm(second)
        self.assertEqual(PurchaseOrder.objects.count(), 2)

    def test_existing_purchase_order_reference(self):
        """An order entered by hand with the bill number also blocks it."""
        order = PurchaseOrder.objects.create(
            supplier=self.acme, supplier_reference='INV1001'
        )
        response = self.confirm(expected_code=409)
        self.assertEqual(
            response.data['duplicate_of'], {'bill': None, 'purchase_order': order.pk}
        )

    def test_unreceived_bills_do_not_block(self):
        """Two bills under review with the same number are not duplicates yet."""
        second = self.reviewed_bill('INV-1001')
        self.assertIsNone(find_duplicate(second))

    def test_same_file_upload(self):
        """Uploading the same bytes again is refused with a pointer to the bill."""
        content = PNG_BYTES + b'same'
        with (
            self.captureOnCommitCallbacks(execute=True),
            mock.patch('bill_scanner.api.queue_extraction'),
        ):
            first = self.client.post(
                f'{API}/bills/',
                {'file': png_upload('a.png', content)},
                format='multipart',
            )
            second = self.client.post(
                f'{API}/bills/',
                {'file': png_upload('b.png', content)},
                format='multipart',
            )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.data['duplicate_of']['bill'], first.data['pk'])

    def test_database_constraint(self):
        """Even bypassing the API, two received bills cannot share a key."""
        self.confirm()
        second = self.reviewed_bill('INV-1001')
        second.status = Bill.Status.COMPLETED
        second.bill_key = 'INV1001'
        with self.assertRaises(IntegrityError), transaction.atomic():
            second.save()


class AuditTest(ConfirmTestBase):
    """Uploads, edits and deletions are audited too."""

    def test_edit_and_delete_entries(self):
        """Header and line edits are recorded; deletion keeps the log."""
        self.patch(f'{API}/bills/{self.bill.pk}/', {'bill_number': 'INV-2'})
        line = self.bill.lines.get(line_number=2)
        self.patch(f'{API}/bills/{self.bill.pk}/lines/{line.pk}/', {'quantity': '3'})

        entries = self.get(f'{API}/bills/{self.bill.pk}/audit/').data
        self.assertEqual([e['action'] for e in entries], ['line_edited', 'edited'])
        self.assertEqual(
            entries[0]['details'], {'line': 2, 'changes': {'quantity': '3.00000'}}
        )
        self.assertEqual(entries[1]['details']['changes'], {'bill_number': 'INV-2'})
        self.assertEqual(entries[1]['user'], self.user.username)

        self.delete(f'{API}/bills/{self.bill.pk}/', expected_code=204)
        deleted = BillAuditLog.objects.get(action=Action.DELETED)
        self.assertIsNone(deleted.bill)
        self.assertIn('INV-2', deleted.bill_label)

    def test_upload_entry(self):
        """Uploads record the file hash."""
        with (
            self.captureOnCommitCallbacks(execute=True),
            mock.patch('bill_scanner.api.queue_extraction'),
        ):
            response = self.client.post(
                f'{API}/bills/',
                {'file': png_upload('u.png', PNG_BYTES + b'u')},
                format='multipart',
            )
        entry = BillAuditLog.objects.get(bill_id=response.data['pk'])
        self.assertEqual(entry.action, Action.UPLOADED)
        self.assertEqual(len(entry.details['file_hash']), 64)
