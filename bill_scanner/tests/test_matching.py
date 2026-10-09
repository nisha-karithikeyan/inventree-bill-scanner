"""Phase 3: matching extracted lines to suppliers and parts."""

from decimal import Decimal
from unittest import TestCase as PlainTestCase

from company.models import Company, ManufacturerPart, SupplierPart
from part.models import Part

from bill_scanner.matching import (
    PartMatcher,
    code_candidates,
    match_bill,
    match_supplier,
    normalize_code,
    normalize_company,
)
from bill_scanner.models import Bill, BillLine
from bill_scanner.tests.base import PluginTestCase

Method = BillLine.MatchMethod


class NormalizeTest(PlainTestCase):
    """Pure helpers."""

    def test_normalize_code(self):
        """Case, spaces and punctuation are ignored."""
        self.assertEqual(normalize_code(' acm-m3/10 '), 'ACMM310')
        self.assertEqual(normalize_code(''), '')

    def test_normalize_company(self):
        """Legal suffixes are dropped."""
        self.assertEqual(
            normalize_company('ACME Components Pvt. Ltd.'), 'acme components'
        )

    def test_code_candidates(self):
        """The SKU comes first, then code-like tokens from the description."""
        found = code_candidates('X1', 'Resistor RC0603FR-0710KL 10k')
        self.assertEqual(found[0], ('X1', 1.0))
        self.assertIn(('RC0603FR-0710KL', 0.95), found)
        # Plain words and pure numbers are not codes.
        self.assertEqual(code_candidates('', 'Red LED 5 pieces 100'), [])


class MatchingDataMixin:
    """A small catalogue: two suppliers, a manufacturer and four parts."""

    @classmethod
    def setUpTestData(cls):
        """Create the catalogue."""
        super().setUpTestData()
        cls.acme = Company.objects.create(name='Acme Components Ltd', is_supplier=True)
        cls.other = Company.objects.create(name='Other Supply Co', is_supplier=True)
        cls.maker = Company.objects.create(name='MakerCorp', is_manufacturer=True)
        Company.objects.create(name='Acme Customer', is_supplier=False)

        def part(name, ipn='', description=''):
            return Part.objects.create(
                name=name, IPN=ipn, description=description, purchaseable=True
            )

        cls.screw = part('M3 x 10 hex socket screw', 'SCR-M3-10')
        cls.led = part('LED red 5mm', 'LED-R-5', 'Through hole indicator LED')
        cls.resistor = part('Resistor 10k 0603')
        cls.cap = part('Capacitor 100nF 0603')
        Part.objects.create(name='Old LED red 5mm', purchaseable=True, active=False)

        cls.acme_screw = SupplierPart.objects.create(
            part=cls.screw, supplier=cls.acme, SKU='ACM-M3-10'
        )
        cls.other_led = SupplierPart.objects.create(
            part=cls.led, supplier=cls.other, SKU='OS-LED-5R'
        )
        cls.acme_led = SupplierPart.objects.create(
            part=cls.led, supplier=cls.acme, SKU='ACM-LED'
        )
        ManufacturerPart.objects.create(
            part=cls.resistor, manufacturer=cls.maker, MPN='RC0603FR-0710KL'
        )


class SupplierMatchTest(MatchingDataMixin, PluginTestCase):
    """match_supplier."""

    def test_exact_and_fuzzy(self):
        """Names match despite suffixes and case; customers are ignored."""
        company, score = match_supplier('ACME COMPONENTS PVT LTD')
        self.assertEqual(company, self.acme)
        self.assertEqual(score, 1.0)

        company, score = match_supplier('Acme Componets')  # Typo.
        self.assertEqual(company, self.acme)
        self.assertLess(score, 1.0)

    def test_no_match(self):
        """Unknown or empty names give no supplier."""
        self.assertEqual(match_supplier('Totally Different GmbH'), (None, 0.0))
        self.assertEqual(match_supplier(''), (None, 0.0))


class PartMatcherTest(MatchingDataMixin, PluginTestCase):
    """PartMatcher.match, rule by rule."""

    def test_supplier_sku(self):
        """This supplier's SKU wins with full confidence, ignoring punctuation."""
        match = PartMatcher(self.acme).match('acm m3 10', 'whatever')
        self.assertEqual(match.part_id, self.screw.pk)
        self.assertEqual(match.supplier_part_id, self.acme_screw.pk)
        self.assertEqual(match.method, Method.SUPPLIER_SKU)
        self.assertEqual(match.confidence, 1.0)

    def test_other_supplier_sku(self):
        """Another supplier's SKU finds the part and this supplier's own SKU."""
        match = PartMatcher(self.acme).match('OS-LED-5R', '')
        self.assertEqual(match.part_id, self.led.pk)
        self.assertEqual(match.supplier_part_id, self.acme_led.pk)
        self.assertEqual(match.method, Method.SKU)
        self.assertEqual(match.confidence, 0.85)

    def test_mpn(self):
        """A manufacturer part number matches."""
        match = PartMatcher(self.acme).match('rc0603fr-0710kl', '')
        self.assertEqual(match.part_id, self.resistor.pk)
        self.assertEqual(match.method, Method.MPN)
        self.assertIsNone(match.supplier_part_id)

    def test_ipn(self):
        """An internal part number matches."""
        match = PartMatcher(None).match('LED-R-5', '')
        self.assertEqual(match.part_id, self.led.pk)
        self.assertEqual(match.method, Method.IPN)

    def test_code_inside_description(self):
        """A code printed in the description matches with a small penalty."""
        match = PartMatcher(self.acme).match('', 'Res RC0603FR-0710KL 1%')
        self.assertEqual(match.part_id, self.resistor.pk)
        self.assertAlmostEqual(match.confidence, 0.92 * 0.95, places=3)

    def test_fuzzy_name(self):
        """Without codes, the description is fuzzy-matched to part names."""
        match = PartMatcher(None).match('', 'Capacitor 100 nF 0603')
        self.assertEqual(match.part_id, self.cap.pk)
        self.assertEqual(match.method, Method.NAME)
        self.assertLessEqual(match.confidence, 0.9)
        self.assertGreater(match.confidence, 0.6)

    def test_fuzzy_prefers_this_suppliers_parts_and_skips_inactive(self):
        """Active parts already bought from this supplier rank first."""
        match = PartMatcher(self.acme).match('', 'Red LED 5mm')
        self.assertEqual(match.part_id, self.led.pk)
        self.assertEqual(match.supplier_part_id, self.acme_led.pk)

    def test_shared_unit_letter_is_not_a_match(self):
        """Sharing a one-letter token such as 'm' must not tie with the real part.

        Regression: WRatio scored 'USB C to C cable 1 m' 85.5 against both the
        cable and 'Jumper wires M-M', and the same-supplier bonus then picked
        the jumper wires.
        """
        cable = Part.objects.create(
            name='USB-C cable 1m', description='USB 2.0, C to C', purchaseable=True
        )
        jumper = Part.objects.create(
            name='Jumper wires M-M', description='20 cm, pack of 40', purchaseable=True
        )
        SupplierPart.objects.create(part=jumper, supplier=self.acme, SKU='ACM-JMP')

        match = PartMatcher(self.acme).match('', 'USB C to C cable 1 m')
        self.assertEqual(match.part_id, cable.pk)
        self.assertEqual(match.method, Method.NAME)

    def test_unknown_code_falls_back_to_name(self):
        """An unknown SKU does not stop name matching."""
        match = PartMatcher(None).match('ZZZ-999', 'M3 x 10 hex socket screw')
        self.assertEqual(match.part_id, self.screw.pk)
        self.assertEqual(match.method, Method.NAME)

    def test_no_match(self):
        """Nothing similar gives an empty match."""
        match = PartMatcher(None).match('', 'Office coffee beans 1kg')
        self.assertIsNone(match.part_id)
        self.assertEqual(match.method, Method.NONE)
        self.assertEqual(match.confidence, 0.0)

    def test_ambiguous_code_is_not_trusted(self):
        """A code shared by several parts is not used."""
        SupplierPart.objects.create(part=self.cap, supplier=self.other, SKU='DUP-1')
        SupplierPart.objects.create(part=self.resistor, supplier=self.acme, SKU='DUP-1')
        match = PartMatcher(None).match('DUP-1', '')
        self.assertIsNone(match.part_id)


class MatchBillTest(MatchingDataMixin, PluginTestCase):
    """match_bill updates a whole bill."""

    def make_lines(self, bill):
        """Three lines: SKU match, name match and a manual choice."""
        bill.lines.create(
            line_number=1, sku='ACM-M3-10', description='Screws', quantity=Decimal(100)
        )
        bill.lines.create(
            line_number=2, description='Capacitor 100nF 0603', quantity=Decimal(10)
        )
        bill.lines.create(
            line_number=3,
            description='Mystery item',
            quantity=1,
            part=self.led,
            match_method=Method.MANUAL,
            match_confidence=1.0,
        )

    def test_matches_supplier_and_lines(self):
        """Supplier is set; manual choices are kept."""
        bill = self.make_bill(
            status=Bill.Status.REVIEW, supplier_name='ACME Components'
        )
        self.make_lines(bill)
        match_bill(bill)

        bill.refresh_from_db()
        self.assertEqual(bill.supplier, self.acme)
        lines = {line.line_number: line for line in bill.lines.all()}
        self.assertEqual(lines[1].supplier_part, self.acme_screw)
        self.assertEqual(lines[1].match_method, Method.SUPPLIER_SKU)
        self.assertEqual(lines[2].part, self.cap)
        self.assertEqual(lines[3].part, self.led)
        self.assertEqual(lines[3].match_method, Method.MANUAL)

    def test_user_supplier_is_kept(self):
        """A supplier chosen by the user is not overwritten."""
        bill = self.make_bill(supplier_name='Acme Components', supplier=self.other)
        match_bill(bill)
        bill.refresh_from_db()
        self.assertEqual(bill.supplier, self.other)

    def test_extraction_task_runs_matching(self):
        """After extraction, lines arrive already matched."""
        from unittest import mock

        from bill_scanner import tasks
        from bill_scanner.tests.base import SAMPLE_REPLY

        self.plugin.set_setting('GEMINI_API_KEY', 'k')
        bill = self.make_bill()
        with mock.patch.object(
            self.plugin, 'request_extraction', return_value=SAMPLE_REPLY
        ):
            tasks.extract_bill(bill.pk)
        bill.refresh_from_db()
        self.assertEqual(bill.supplier, self.acme)
        first = bill.lines.get(line_number=1)
        self.assertEqual(first.part, self.screw)
        second = bill.lines.get(line_number=2)
        self.assertEqual(second.part, self.led)
