"""Phase 4: review endpoints and the UI panel registration."""

from decimal import Decimal

from django.urls import reverse

from company.models import Company, SupplierPart
from part.models import Part

from bill_scanner.models import Bill, BillLine
from bill_scanner.tests.base import API, PluginTestCase

Method = BillLine.MatchMethod


class ReviewApiTest(PluginTestCase):
    """PATCH bill headers and lines."""

    @classmethod
    def setUpTestData(cls):
        """Two suppliers and two parts."""
        super().setUpTestData()
        cls.acme = Company.objects.create(name='Acme', is_supplier=True)
        cls.other = Company.objects.create(name='Other', is_supplier=True)
        cls.screw = Part.objects.create(name='Screw M3', purchaseable=True)
        cls.nut = Part.objects.create(name='Nut M3', purchaseable=True)
        cls.acme_screw = SupplierPart.objects.create(
            part=cls.screw, supplier=cls.acme, SKU='A-SCREW'
        )
        cls.other_nut = SupplierPart.objects.create(
            part=cls.nut, supplier=cls.other, SKU='O-NUT'
        )

    def setUp(self):
        """A bill under review with one SKU line and one unmatched line."""
        super().setUp()
        self.bill = self.make_bill(status=Bill.Status.REVIEW, supplier=self.other)
        self.sku_line = self.bill.lines.create(
            line_number=1, sku='A-SCREW', description='screw', quantity=Decimal(5)
        )
        self.free_line = self.bill.lines.create(
            line_number=2, description='Mystery', quantity=Decimal(1)
        )

    def line_url(self, line):
        """Detail URL for one line."""
        return f'{API}/bills/{self.bill.pk}/lines/{line.pk}/'

    def test_pick_part_marks_manual(self):
        """Choosing a part makes a manual, fully trusted match."""
        response = self.patch(
            self.line_url(self.free_line), {'part': self.nut.pk}, expected_code=200
        )
        self.assertEqual(response.data['match_method'], Method.MANUAL)
        self.assertEqual(response.data['match_confidence'], 1.0)
        self.assertEqual(response.data['part_detail']['name'], 'Nut M3')

    def test_clearing_part_resets_match(self):
        """Removing the part clears the match."""
        self.free_line.part = self.nut
        self.free_line.save()
        response = self.patch(self.line_url(self.free_line), {'part': None})
        self.assertEqual(response.data['match_method'], Method.NONE)
        self.assertEqual(response.data['match_confidence'], 0.0)

    def test_edit_quantity_price_and_skip(self):
        """Corrections are stored without touching the match."""
        self.patch(
            self.line_url(self.free_line),
            {'quantity': '12.5', 'unit_price': '0.20', 'skip': True},
            expected_code=200,
        )
        self.free_line.refresh_from_db()
        self.assertEqual(self.free_line.quantity, Decimal('12.5'))
        self.assertEqual(self.free_line.unit_price, Decimal('0.2'))
        self.assertTrue(self.free_line.skip)
        self.assertEqual(self.free_line.match_method, Method.NONE)

    def test_rejects_bad_values(self):
        """Zero quantity, negative price and unpurchaseable parts are refused."""
        url = self.line_url(self.free_line)
        self.patch(url, {'quantity': '0'}, expected_code=400)
        self.patch(url, {'unit_price': '-1'}, expected_code=400)
        locked = Part.objects.create(name='Made here', purchaseable=False)
        self.patch(url, {'part': locked.pk}, expected_code=400)

    def test_supplier_part_must_fit(self):
        """A supplier part must belong to the chosen part and the bill's supplier."""
        url = self.line_url(self.free_line)
        self.patch(
            url,
            {'part': self.nut.pk, 'supplier_part': self.acme_screw.pk},
            expected_code=400,
        )
        # acme_screw is from Acme, but the bill's supplier is Other.
        self.patch(url, {'supplier_part': self.acme_screw.pk}, expected_code=400)
        # Other's nut is fine, and sets the part too.
        response = self.patch(
            url, {'supplier_part': self.other_nut.pk}, expected_code=200
        )
        self.assertEqual(response.data['part'], self.nut.pk)

    def test_new_part_drops_stale_supplier_part(self):
        """Changing the part clears a supplier part for the old part."""
        self.free_line.part = self.nut
        self.free_line.supplier_part = self.other_nut
        self.free_line.save()
        response = self.patch(self.line_url(self.free_line), {'part': self.screw.pk})
        self.assertIsNone(response.data['supplier_part'])

    def test_changing_supplier_rematches_lines(self):
        """A corrected supplier re-runs matching, keeping manual choices."""
        self.free_line.part = self.nut
        self.free_line.match_method = Method.MANUAL
        self.free_line.save()

        response = self.patch(
            f'{API}/bills/{self.bill.pk}/',
            {'supplier': self.acme.pk},
            expected_code=200,
        )
        self.assertEqual(response.data['supplier_confidence'], 1.0)
        self.sku_line.refresh_from_db()
        self.free_line.refresh_from_db()
        self.assertEqual(self.sku_line.supplier_part, self.acme_screw)
        self.assertEqual(self.sku_line.match_method, Method.SUPPLIER_SKU)
        self.assertEqual(self.free_line.part, self.nut)

    def test_header_edits(self):
        """Bill number and date can be corrected; extracted data cannot."""
        self.patch(
            f'{API}/bills/{self.bill.pk}/',
            {'bill_number': 'INV-9', 'bill_date': '2026-10-01', 'extracted': {}},
            expected_code=200,
        )
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.bill_number, 'INV-9')
        self.assertEqual(str(self.bill.bill_date), '2026-10-01')
        self.assertIsNone(self.bill.extracted)

    def test_only_review_bills_are_editable(self):
        """Bills still extracting or already received are locked."""
        for status in (Bill.Status.PROCESSING, Bill.Status.COMPLETED):
            Bill.objects.filter(pk=self.bill.pk).update(status=status)
            self.patch(self.line_url(self.free_line), {'skip': True}, expected_code=400)
            self.patch(
                f'{API}/bills/{self.bill.pk}/', {'bill_number': 'x'}, expected_code=400
            )

    def test_edit_needs_change_permission(self):
        """View-only users can read but not edit."""
        self.clearRoles()
        self.assignRole('purchase_order.view')
        self.get(f'{API}/bills/{self.bill.pk}/', expected_code=200)
        self.patch(self.line_url(self.free_line), {'skip': True}, expected_code=403)

    def test_lines_of_other_bills_are_hidden(self):
        """A line id from another bill is not found."""
        other_bill = self.make_bill(status=Bill.Status.REVIEW)
        url = f'{API}/bills/{other_bill.pk}/lines/{self.free_line.pk}/'
        self.patch(url, {'skip': True}, expected_code=404)


class PanelTest(PluginTestCase):
    """The review panel is offered on the Purchasing page."""

    def panels(self, target_model):
        """Ask InvenTree's UI API for panels on a page."""
        url = reverse('api-plugin-ui-feature-list', kwargs={'feature': 'panel'})
        response = self.get(url, {'target_model': target_model}, expected_code=200)
        return [p for p in response.data if p['plugin_name'] == 'bill-scanner']

    def test_panel_on_purchasing_page(self):
        """The panel points at the bundled JS with its settings as context."""
        self.plugin.set_setting('GEMINI_API_KEY', 'secret-xyz')
        panels = self.panels('purchasing')
        self.assertEqual(len(panels), 1)
        panel = panels[0]
        self.assertTrue(
            panel['source'].endswith('BillScanner.js:renderBillScannerPanel'),
            panel['source'],
        )
        context = panel['context']
        self.assertEqual(context['api'], '/plugin/bill-scanner/api')
        self.assertEqual(context['low_confidence'], 0.75)
        self.assertTrue(context['has_api_key'])
        self.assertTrue(context['can_confirm'])
        self.assertNotIn('secret-xyz', str(panel))

    def test_not_on_other_pages(self):
        """Other pages do not get the panel."""
        self.assertEqual(self.panels('part'), [])

    def test_hidden_without_role(self):
        """Users without purchase order access do not see it."""
        self.clearRoles()
        self.assertEqual(self.panels('purchasing'), [])

    def test_confirm_needs_stock_role(self):
        """can_confirm is false without stock.add."""
        self.clearRoles()
        for perm in ('view', 'add', 'change'):
            self.assignRole(f'purchase_order.{perm}')
        context = self.panels('purchasing')[0]['context']
        self.assertTrue(context['can_edit'])
        self.assertFalse(context['can_confirm'])
