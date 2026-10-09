"""Tests for the evaluation scorer.

.venv/bin/python -m unittest discover eval
"""

import json
from pathlib import Path
from unittest import TestCase

from scoring import (
    compare_header,
    pair_lines,
    part_matches,
    price_matches,
    render_markdown,
    score_bill,
    summarise,
)

TEMPLATE = json.loads((Path(__file__).parent / 'template.json').read_text())


def extracted_line(description, quantity, price, part=None, **extra):
    """A line as run_eval.snapshot() writes it."""
    return {
        'description': description,
        'sku': extra.get('sku', ''),
        'quantity': str(quantity),
        'unit_price': None if price is None else str(price),
        'confidence': extra.get('confidence', 0.95),
        'part': None if part is None else {'pk': 1, 'IPN': part, 'name': part},
        'match_method': extra.get('method', 'supplier_sku' if part else ''),
        'match_confidence': extra.get('match_confidence', 1.0 if part else 0.0),
    }


def perfect_snapshot():
    """What a flawless extraction of template.json looks like."""
    return {
        'status': 'review',
        'attempts': 1,
        'supplier_name': 'Demo Electronics Supply Ltd',
        'bill_number': 'des 2057',
        'bill_date': '2026-10-02',
        'currency': 'usd',
        'supplier': 'Demo Electronics Supply',
        'lines': [
            extracted_line('Hex socket screw M3x10', '100', '0.05', 'SCR-M3-10'),
            extracted_line('Red LED 5 mm diffused', '50.00000', '0.080000', 'LED-R-5'),
            extracted_line('Packing and handling', '1', '2.5'),
        ],
    }


class CompareTest(TestCase):
    """Field comparisons."""

    def test_header_fields(self):
        """Suffixes, case and punctuation do not count as errors."""
        self.assertTrue(compare_header('supplier_name', 'Acme Ltd', 'ACME limited'))
        self.assertFalse(compare_header('supplier_name', 'Acme Ltd', 'Apex Ltd'))
        self.assertTrue(compare_header('bill_number', 'INV-001', 'inv 001'))
        self.assertFalse(compare_header('bill_number', 'INV-001', 'INV-007'))
        self.assertTrue(compare_header('currency', 'EUR', 'eur'))
        self.assertTrue(compare_header('bill_date', None, None))
        self.assertFalse(compare_header('bill_date', '2026-10-02', '2026-02-10'))

    def test_prices(self):
        """Half a percent or one cent of slack; missing must stay missing."""
        self.assertTrue(price_matches(0.05, '0.050000'))
        self.assertTrue(price_matches(100, '100.4'))
        self.assertFalse(price_matches(100, '101'))
        self.assertFalse(price_matches(0.05, None))
        self.assertTrue(price_matches(None, None))

    def test_parts(self):
        """Expected part by IPN or name; None expects no part."""
        part = {'IPN': 'LED-R-5', 'name': 'LED red 5mm'}
        self.assertTrue(part_matches('led-r-5', part))
        self.assertTrue(part_matches('LED red 5mm', part))
        self.assertFalse(part_matches('LED-G-5', part))
        self.assertTrue(part_matches(None, None))
        self.assertFalse(part_matches(None, part))
        self.assertFalse(part_matches('LED-R-5', None))

    def test_pairing_ignores_order(self):
        """Lines are paired by content, not by position."""
        truth = [{'description': 'Red LED'}, {'description': 'M3 screw', 'sku': 'S1'}]
        got = [{'description': 'Screw', 'sku': 's-1'}, {'description': 'LED red'}]
        self.assertEqual(pair_lines(truth, got), [(0, 1), (1, 0)])


class ScoreBillTest(TestCase):
    """Scoring a whole bill."""

    def test_perfect_bill(self):
        """A flawless extraction has no failures."""
        result = score_bill('a.png', TEMPLATE, perfect_snapshot())
        self.assertEqual(result.reasons, [])
        self.assertTrue(all(result.fields.values()))
        self.assertTrue(result.supplier_ok)
        self.assertTrue(all(line.ok for line in result.lines))

    def test_reports_reasons(self):
        """Wrong values, wrong parts, missing and extra lines are all explained."""
        got = perfect_snapshot()
        got['bill_number'] = 'DES-2051'
        got['lines'][0] = extracted_line(
            'Hex socket screw M3x10', '10', '0.05', 'SCR-M3-12', method='name'
        )
        del got['lines'][1]
        got['lines'].append(extracted_line('Sales tax 8%', '1', '1.20'))
        result = score_bill('b.png', TEMPLATE, got)

        text = '\n'.join(result.reasons)
        self.assertIn("bill_number: expected 'DES-2057'", text)
        self.assertIn('quantity 100 read as 10', text)
        self.assertIn("matched 'SCR-M3-12' by name, expected 'SCR-M3-10'", text)
        self.assertIn('not extracted', text)
        self.assertIn("extra line not on the bill: 'Sales tax 8%'", text)

    def test_failed_extraction(self):
        """A failed bill scores zero on every field and line."""
        got = {'status': 'failed', 'error': 'HTTP 403', 'attempts': 1, 'lines': []}
        result = score_bill('c.png', TEMPLATE, got)
        self.assertFalse(any(result.fields.values()))
        self.assertFalse(any(line.ok for line in result.lines))
        self.assertIn('extraction ended as failed: HTTP 403', result.reasons[0])


class SummaryTest(TestCase):
    """Aggregated numbers and the markdown report."""

    def test_summary_and_report(self):
        """Rates, confidence split and flagging are computed over all bills."""
        bad = perfect_snapshot()
        bad['lines'][1] = extracted_line(
            'Red LED 5 mm diffused', '5', '0.08', 'LED-R-5', confidence=0.4
        )
        results = [
            score_bill('good.png', TEMPLATE, perfect_snapshot()),
            score_bill('bad.png', TEMPLATE, bad),
        ]
        summary = summarise(results, threshold=0.75)

        self.assertEqual(summary['bills'], 2)
        self.assertEqual(summary['truth_lines'], 6)
        self.assertAlmostEqual(summary['line_accuracy'], 5 / 6)
        self.assertEqual(summary['match_accuracy'], (1.0, 6))
        self.assertEqual(summary['wrong_lines'], 1)
        self.assertEqual(summary['wrong_flagged'], 1.0)
        self.assertEqual(summary['right_flagged'], 0.0)
        self.assertAlmostEqual(summary['read_confidence_wrong'], 0.4)

        report = render_markdown(
            summary, results, {'when': 'now', 'model': 'm', 'version': '0'}
        )
        self.assertIn('**Line fully correct: 83.3%**', report)
        self.assertIn('### bad.png', report)
        self.assertNotIn('### good.png', report)
