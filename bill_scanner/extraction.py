"""Structured bill data: the schema sent to Gemini and the parser for its reply."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

PROMPT = """You are reading a supplier bill (invoice, delivery note or receipt).
Extract the supplier name, the bill or invoice number, the bill date and every
purchased line item. For each line give the description exactly as printed,
the supplier's item code or SKU if one is printed (otherwise an empty string),
the quantity, and the unit price before tax. If only a line total is printed,
divide it by the quantity. Write dates as YYYY-MM-DD. Give the ISO 4217
currency code if you can tell it. Do not include tax, shipping or discount
summary rows as line items. For every value you are unsure about, lower the
confidence score for that line (0 = guess, 1 = clearly printed)."""

RESPONSE_SCHEMA: dict[str, Any] = {
    'type': 'OBJECT',
    'properties': {
        'supplier_name': {'type': 'STRING'},
        'bill_number': {'type': 'STRING'},
        'bill_date': {'type': 'STRING', 'description': 'YYYY-MM-DD'},
        'currency': {'type': 'STRING', 'description': 'ISO 4217 code'},
        'lines': {
            'type': 'ARRAY',
            'items': {
                'type': 'OBJECT',
                'properties': {
                    'description': {'type': 'STRING'},
                    'sku': {'type': 'STRING'},
                    'quantity': {'type': 'NUMBER'},
                    'unit_price': {'type': 'NUMBER'},
                    'confidence': {'type': 'NUMBER'},
                },
                'required': ['description', 'quantity', 'confidence'],
            },
        },
    },
    'required': ['supplier_name', 'bill_number', 'lines'],
}


class ExtractionError(ValueError):
    """The model's reply does not describe a usable bill."""


@dataclass
class ExtractedLine:
    """One parsed line item."""

    description: str
    sku: str
    quantity: Decimal
    unit_price: Decimal | None
    confidence: float


@dataclass
class ExtractedBill:
    """The parsed bill header and its lines."""

    supplier_name: str
    bill_number: str
    bill_date: date | None
    currency: str
    lines: list[ExtractedLine] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        """Return a JSON-safe dict for storage."""
        data = asdict(self)
        data['bill_date'] = self.bill_date.isoformat() if self.bill_date else None
        for line in data['lines']:
            line['quantity'] = str(line['quantity'])
            if line['unit_price'] is not None:
                line['unit_price'] = str(line['unit_price'])
        return data


_DATE_FORMATS = ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y', '%d %b %Y', '%d %B %Y')


def parse_date(value: Any) -> date | None:
    """Parse a bill date, returning None when it is missing or unreadable."""
    text = str(value or '').strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_decimal(value: Any) -> Decimal | None:
    """Parse a number that may carry currency symbols or thousands separators.

    Accepts both '1,234.50' and '1.234,50'. Returns None for empty or bad input.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float | Decimal):
        return Decimal(str(value))
    text = re.sub(r'[^\d,.\-]', '', str(value))
    if not text:
        return None
    if ',' in text and '.' in text:
        # Whichever separator comes last is the decimal point.
        if text.rfind(',') > text.rfind('.'):
            text = text.replace('.', '').replace(',', '.')
        else:
            text = text.replace(',', '')
    elif ',' in text:
        # A single comma followed by exactly three digits is a thousands separator.
        head, _, tail = text.rpartition(',')
        point = '' if len(tail) == 3 else '.'
        text = f'{head.replace(",", "")}{point}{tail}'
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def clamp_confidence(value: Any) -> float:
    """Force a confidence score into the range 0..1."""
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if score > 1:
        score = score / 100  # The model sometimes answers in percent.
    return max(0.0, min(1.0, score))


def _clean_text(value: Any, limit: int) -> str:
    return ' '.join(str(value or '').split())[:limit]


def parse_line(raw: dict[str, Any]) -> ExtractedLine | None:
    """Parse one line, dropping rows without a positive quantity."""
    quantity = parse_decimal(raw.get('quantity'))
    if quantity is None or quantity <= 0:
        return None
    unit_price = parse_decimal(raw.get('unit_price'))
    if unit_price is not None and unit_price < 0:
        unit_price = None
    return ExtractedLine(
        description=_clean_text(raw.get('description'), 500),
        sku=_clean_text(raw.get('sku'), 100),
        quantity=quantity,
        unit_price=unit_price,
        confidence=clamp_confidence(raw.get('confidence')),
    )


def parse_extraction(data: Any) -> ExtractedBill:
    """Validate and normalise the JSON object returned by Gemini."""
    if not isinstance(data, dict):
        raise ExtractionError('Expected a JSON object')
    raw_lines = data.get('lines')
    if not isinstance(raw_lines, list):
        raise ExtractionError('No line items found')

    lines = [
        line
        for raw in raw_lines
        if isinstance(raw, dict) and (line := parse_line(raw)) is not None
    ]
    if not lines:
        raise ExtractionError('No line items with a quantity were found')

    currency = _clean_text(data.get('currency'), 10).upper()
    return ExtractedBill(
        supplier_name=_clean_text(data.get('supplier_name'), 255),
        bill_number=_clean_text(data.get('bill_number'), 100),
        bill_date=parse_date(data.get('bill_date')),
        currency=currency if re.fullmatch(r'[A-Z]{3}', currency) else '',
        lines=lines,
    )
