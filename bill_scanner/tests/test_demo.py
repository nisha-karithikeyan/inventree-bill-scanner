"""The demo data (dev/demo.py) makes the sample bill match well.

Skipped when the package is installed without the dev/ folder.
"""

from decimal import Decimal
from pathlib import Path
from unittest import skipUnless

from company.models import Company
from part.models import Part

from bill_scanner.matching import PartMatcher, match_supplier
from bill_scanner.tests.base import PluginTestCase

DEMO = Path(__file__).resolve().parents[2] / 'dev' / 'demo.py'


def load_demo() -> dict:
    """Run dev/demo.py's definitions without calling main()."""
    namespace: dict = {'__name__': 'demo'}
    exec(compile(DEMO.read_text(), str(DEMO), 'exec'), namespace)
    return namespace


@skipUnless(DEMO.exists(), 'dev/demo.py is not available')
class DemoDataTest(PluginTestCase):
    """Seeding is idempotent and every sample line matches its expected part."""

    def setUp(self):
        """Seed the demo twice: the second run must change nothing."""
        super().setUp()
        self.demo = load_demo()
        self.demo['seed']()
        self.demo['seed']()

    def test_catalogue(self):
        """12 parts, each with stock on hand, from one supplier."""
        ipns = [row[1] for row in self.demo['PARTS']]
        parts = Part.objects.filter(IPN__in=ipns)
        self.assertEqual(parts.count(), 12)
        for part in parts:
            self.assertGreater(part.total_stock, 0, part.IPN)
        self.assertTrue(Company.objects.get(name='Brightline Components').is_supplier)

    def test_sample_bill_matches(self):
        """Supplier and every line match, using each method at least once."""
        supplier, confidence = match_supplier(self.demo['BILL']['supplier_name'])
        self.assertEqual(supplier.name, 'Brightline Components')
        self.assertGreaterEqual(confidence, 0.9)

        matcher = PartMatcher(supplier)
        methods = set()
        for code, description, _, _, ipn in self.demo['LINES']:
            with self.subTest(description=description):
                found = matcher.match(code, description)
                self.assertEqual(Part.objects.get(pk=found.part_id).IPN, ipn)
                methods.add(found.method)
        self.assertEqual(methods, {'supplier_sku', 'mpn', 'name'})

    def test_bill_and_truth_files(self):
        """The drawn bill is an A4 PNG and the truth file adds up."""
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            image = self.demo['draw_bill'](Path(folder))
            truth = json.loads(self.demo['write_truth'](Path(folder)).read_text())
            self.assertTrue(image.read_bytes().startswith(b'\x89PNG'))

        self.assertEqual(truth['bill_number'], 'BRL-INV-24817')
        self.assertEqual(len(truth['lines']), 8)
        subtotal = sum(
            Decimal(str(line['unit_price'])) * line['quantity']
            for line in truth['lines']
        )
        self.assertEqual(subtotal, Decimal('53.50'))
