"""Seed a clean demo: one supplier, 12 parts with stock, and a sample bill.

Run with: dev/demo.sh (or dev/demo.sh --fresh to start from an empty database).
All names, codes and numbers are fictional.

The sample bill is drawn to docs/demo/sample-bill.png with its ground truth in
docs/demo/sample-bill.json (the eval/ format). Its lines are chosen to show
every match method: supplier SKU, manufacturer part number, and fuzzy name.
Running the script twice changes nothing.
"""

from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.db import transaction

from company.models import Company, ManufacturerPart, SupplierPart
from part.models import Part, PartCategory
from PIL import Image, ImageDraw, ImageFont
from stock.models import StockItem, StockLocation

SUPPLIER = 'Brightline Components'
MANUFACTURER = 'Fictive Semiconductors'

# name, IPN, description, supplier SKU, MPN, stock on hand
PARTS = [
    (
        'M3 x 10 hex socket screw',
        'SCR-M3-10',
        'Stainless A2, DIN 912',
        'BRL-M3-10',
        None,
        340,
    ),
    ('M3 hex nut', 'NUT-M3', 'Stainless A2, DIN 934', 'BRL-NM3', None, 500),
    (
        'Resistor 10k 0603',
        'RES-10K-0603',
        '1% 0.1 W thick film',
        'BRL-R10K-0603',
        None,
        1200,
    ),
    (
        'Capacitor 100nF 0603',
        'CAP-100N-0603',
        'X7R 50 V ceramic',
        'BRL-C100N-0603',
        None,
        800,
    ),
    ('LED red 5mm', 'LED-R-5', 'Diffused, 20 mA', None, None, 60),
    ('LED green 5mm', 'LED-G-5', 'Diffused, 20 mA', None, None, 45),
    (
        'Voltage regulator 3.3V',
        'VREG-3V3',
        'LDO 800 mA, SOT-223',
        None,
        'FS1117-3.3',
        25,
    ),
    (
        'Microcontroller FS328',
        'MCU-FS328',
        '8-bit, TQFP-32',
        'BRL-FS328',
        'FS328-AU',
        12,
    ),
    ('USB-C cable 1m', 'CBL-USBC-1M', 'USB 2.0, C to C', None, None, 8),
    ('Header pins 1x40', 'HDR-1X40', '2.54 mm pitch, male', 'BRL-HDR40', None, 30),
    ('Heat shrink tube 3mm', 'HST-3MM', 'Black, 1 m length', None, None, 15),
    ('Jumper wires M-M', 'JMP-MM-20', '20 cm, pack of 40', 'BRL-JMP-MM', None, 10),
]

BILL = {
    'supplier_name': f'{SUPPLIER} Ltd',
    'bill_number': 'BRL-INV-24817',
    'bill_date': '2026-10-06',
    'currency': 'USD',
}
FREIGHT = Decimal('6.50')
TAX_RATE = Decimal('0.08')

# code printed on the bill, description as printed, qty, unit price, expected IPN
LINES = [
    ('BRL-M3-10', 'Hex socket screw M3x10 A2', 200, '0.045', 'SCR-M3-10'),
    ('BRL-NM3', 'Hex nut M3 stainless', 200, '0.020', 'NUT-M3'),
    ('BRL-R10K-0603', 'Res 10k 1% 0603', 500, '0.008', 'RES-10K-0603'),
    ('BRL-C100N-0603', 'Cap 100nF X7R 0603', 500, '0.012', 'CAP-100N-0603'),
    ('', 'Red LED 5mm diffused', 50, '0.090', 'LED-R-5'),
    ('FS1117-3.3', 'LDO regulator 3.3V SOT-223', 20, '0.350', 'VREG-3V3'),
    ('', 'USB C to C cable 1 m', 5, '2.800', 'CBL-USBC-1M'),
    ('BRL-HDR40', 'Pin header 1x40 2.54mm', 20, '0.250', 'HDR-1X40'),
]


def money(value: Decimal) -> str:
    """Two decimals, as printed on a bill."""
    return str(value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


@transaction.atomic
def seed() -> None:
    """Create the supplier, parts, supplier parts and stock (idempotent)."""
    supplier, _ = Company.objects.get_or_create(
        name=SUPPLIER, defaults={'is_supplier': True, 'currency': 'USD'}
    )
    maker, _ = Company.objects.get_or_create(
        name=MANUFACTURER, defaults={'is_manufacturer': True, 'is_supplier': False}
    )
    category, _ = PartCategory.objects.get_or_create(name='Demo components')
    store, _ = StockLocation.objects.get_or_create(name='Main store')
    shelf, _ = StockLocation.objects.get_or_create(name='Shelf A', parent=store)

    for name, ipn, description, sku, mpn, on_hand in PARTS:
        part, _ = Part.objects.get_or_create(
            IPN=ipn,
            defaults={
                'name': name,
                'description': description,
                'category': category,
                'purchaseable': True,
                'component': True,
            },
        )
        manufacturer_part = None
        if mpn:
            manufacturer_part, _ = ManufacturerPart.objects.get_or_create(
                part=part, manufacturer=maker, MPN=mpn
            )
        if sku:
            SupplierPart.objects.get_or_create(
                part=part,
                supplier=supplier,
                SKU=sku,
                defaults={'manufacturer_part': manufacturer_part},
            )
        if not StockItem.objects.filter(part=part, location=shelf).exists():
            StockItem.objects.create(part=part, location=shelf, quantity=on_hand)


def font(size: int, bold: bool = False):
    """DejaVu if installed (nicer), else Pillow's built-in font."""
    name = 'DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'
    for folder in ('/usr/share/fonts/truetype/dejavu', '/usr/share/fonts/dejavu'):
        path = Path(folder) / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def draw_bill(out: Path) -> Path:
    """Draw the sample bill as an A4 page at 150 dpi."""
    page = Image.new('RGB', (1240, 1754), 'white')
    draw = ImageDraw.Draw(page)
    ink, grey = (25, 25, 25), (110, 110, 110)

    draw.text((90, 90), BILL['supplier_name'], fill=ink, font=font(44, bold=True))
    for i, text in enumerate(
        (
            'Unit 4, Example Trade Park',
            'Sampletown ST1 2AB',
            'DEMO DATA - not a real company',
        )
    ):
        draw.text((90, 155 + i * 30), text, fill=grey, font=font(22))
    draw.text((820, 90), 'INVOICE', fill=ink, font=font(48, bold=True))
    draw.text((820, 160), f'Invoice no: {BILL["bill_number"]}', fill=ink, font=font(24))
    draw.text((820, 195), 'Date: 06 Oct 2026', fill=ink, font=font(24))
    draw.text((820, 230), 'Currency: USD', fill=ink, font=font(24))
    draw.text(
        (90, 300), 'Bill to: Demo Workshop, 1 Sample Street', fill=ink, font=font(24)
    )

    columns = (
        ('Item code', 90),
        ('Description', 330),
        ('Qty', 780),
        ('Unit price', 880),
        ('Amount', 1060),
    )
    y = 400
    draw.rectangle((80, y - 12, 1160, y + 40), fill=(235, 238, 242))
    for title, x in columns:
        draw.text((x, y), title, fill=ink, font=font(22, bold=True))

    subtotal = Decimal(0)
    for code, description, qty, price, _ in LINES:
        y += 62
        amount = Decimal(qty) * Decimal(price)
        subtotal += amount
        values = (code, description, str(qty), price, money(amount))
        for value, (_, x) in zip(values, columns, strict=True):
            draw.text((x, y), value, fill=ink, font=font(22))
        draw.line((80, y + 45, 1160, y + 45), fill=(220, 220, 220), width=1)

    tax = (subtotal + FREIGHT) * TAX_RATE
    y += 90
    for label, value in (
        ('Subtotal', subtotal),
        ('Freight', FREIGHT),
        (f'Sales tax {int(TAX_RATE * 100)}%', tax),
    ):
        draw.text((820, y), label, fill=ink, font=font(24))
        draw.text((1060, y), money(value), fill=ink, font=font(24))
        y += 40
    draw.line((800, y + 5, 1160, y + 5), fill=ink, width=2)
    draw.text((820, y + 20), 'Total USD', fill=ink, font=font(26, bold=True))
    draw.text(
        (1060, y + 20),
        money(subtotal + FREIGHT + tax),
        fill=ink,
        font=font(26, bold=True),
    )
    draw.text(
        (90, 1620),
        'Payment due within 30 days. Thank you for your order.',
        fill=grey,
        font=font(20),
    )

    out.mkdir(parents=True, exist_ok=True)
    path = out / 'sample-bill.png'
    page.save(path, 'PNG', optimize=True)
    return path


def write_truth(out: Path) -> Path:
    """Ground truth for the sample bill, in the eval/ format."""
    import json

    truth = {
        **BILL,
        'expected_supplier': SUPPLIER,
        'lines': [
            {
                'description': description,
                'sku': code,
                'quantity': qty,
                'unit_price': float(price),
                'expected_part': ipn,
            }
            for code, description, qty, price, ipn in LINES
        ],
    }
    path = out / 'sample-bill.json'
    path.write_text(json.dumps(truth, indent=2) + '\n')
    return path


def main(plugin_root: str) -> None:
    """Seed the data, draw the bill and show what the demo contains."""
    if not get_user_model().objects.filter(is_superuser=True).exists():
        raise SystemExit('Run dev/setup.sh first.')
    seed()
    out = Path(plugin_root) / 'docs' / 'demo'
    print(f'Supplier: {SUPPLIER}')
    print('Parts (IPN, name, stock):')
    for ipn in [row[1] for row in PARTS]:
        part = Part.objects.get(IPN=ipn)
        print(f'  {ipn:<14} {part.name:<28} {part.total_stock}')
    print(f'Sample bill: {draw_bill(out)}')
    print(f'Ground truth: {write_truth(out)}')
