"""Phase 2: parsing Gemini's JSON into a validated bill."""

from datetime import date
from decimal import Decimal
from unittest import TestCase

from bill_scanner.extraction import (
    ExtractionError,
    clamp_confidence,
    parse_date,
    parse_decimal,
    parse_extraction,
    parse_line,
)
from bill_scanner.tests.base import SAMPLE_REPLY


class ParseDecimalTest(TestCase):
    """Numbers as printed on real bills."""

    def test_plain_numbers(self):
        """Ints, floats and numeric strings."""
        self.assertEqual(parse_decimal(3), Decimal('3'))
        self.assertEqual(parse_decimal(0.1), Decimal('0.1'))
        self.assertEqual(parse_decimal('12.50'), Decimal('12.50'))

    def test_currency_and_separators(self):
        """Symbols, thousands separators and decimal commas."""
        self.assertEqual(parse_decimal('$1,234.50'), Decimal('1234.50'))
        self.assertEqual(parse_decimal('1.234,50 €'), Decimal('1234.50'))
        self.assertEqual(parse_decimal('0,12'), Decimal('0.12'))
        self.assertEqual(parse_decimal('1,234'), Decimal('1234'))
        self.assertEqual(parse_decimal('1,234,567'), Decimal('1234567'))
        self.assertEqual(parse_decimal('₹ 2,50,000.00'), Decimal('250000.00'))

    def test_bad_values(self):
        """Missing or junk input becomes None."""
        for value in (None, '', 'n/a', True, '--'):
            self.assertIsNone(parse_decimal(value), value)


class ParseDateTest(TestCase):
    """Bill dates."""

    def test_formats(self):
        """ISO and common day-first formats."""
        expected = date(2026, 9, 30)
        for text in ('2026-09-30', '30/09/2026', '30.09.2026', '30 Sep 2026'):
            self.assertEqual(parse_date(text), expected, text)

    def test_unreadable(self):
        """Unknown formats give None instead of failing the bill."""
        self.assertIsNone(parse_date('sometime'))
        self.assertIsNone(parse_date(None))


class ConfidenceTest(TestCase):
    """Confidence is always 0..1."""

    def test_clamp(self):
        """Out of range, percent and junk values."""
        self.assertEqual(clamp_confidence(0.7), 0.7)
        self.assertEqual(clamp_confidence(85), 0.85)
        self.assertEqual(clamp_confidence(-1), 0.0)
        self.assertEqual(clamp_confidence('x'), 0.0)
        self.assertEqual(clamp_confidence(None), 0.0)


class ParseExtractionTest(TestCase):
    """Whole replies."""

    def test_sample_reply(self):
        """The sample reply parses into two clean lines."""
        bill = parse_extraction(SAMPLE_REPLY)
        self.assertEqual(bill.supplier_name, 'Acme Components Ltd')
        self.assertEqual(bill.bill_number, 'INV-1001')
        self.assertEqual(bill.bill_date, date(2026, 9, 30))
        self.assertEqual(bill.currency, 'USD')
        self.assertEqual(len(bill.lines), 2)
        self.assertEqual(bill.lines[1].unit_price, Decimal('0.12'))
        self.assertEqual(bill.lines[1].quantity, Decimal('25'))

    def test_to_json_is_serialisable(self):
        """Stored JSON uses strings for decimals and ISO dates."""
        data = parse_extraction(SAMPLE_REPLY).to_json()
        self.assertEqual(data['bill_date'], '2026-09-30')
        self.assertEqual(data['lines'][0]['quantity'], '100')
        self.assertEqual(data['lines'][0]['unit_price'], '0.05')

    def test_drops_rows_without_quantity(self):
        """Summary rows such as tax lines are ignored."""
        self.assertIsNone(parse_line({'description': 'VAT', 'quantity': 0}))
        self.assertIsNone(parse_line({'description': 'Total'}))

    def test_negative_price_is_dropped(self):
        """A negative unit price is treated as unknown."""
        line = parse_line({'description': 'x', 'quantity': 1, 'unit_price': -5})
        self.assertIsNone(line.unit_price)

    def test_collapses_whitespace_and_bad_currency(self):
        """Text is tidied and invalid currency codes are removed."""
        bill = parse_extraction(
            {
                'supplier_name': '  Acme \n Ltd ',
                'bill_number': 'A1',
                'currency': 'dollars',
                'lines': [{'description': 'a\tb', 'quantity': 1}],
            }
        )
        self.assertEqual(bill.supplier_name, 'Acme Ltd')
        self.assertEqual(bill.lines[0].description, 'a b')
        self.assertEqual(bill.currency, '')

    def test_rejects_unusable_replies(self):
        """Non-objects and replies without lines raise ExtractionError."""
        for reply in ([], 'text', {'lines': 'x'}, {'lines': [{'quantity': 0}]}):
            with self.assertRaises(ExtractionError):
                parse_extraction(reply)
