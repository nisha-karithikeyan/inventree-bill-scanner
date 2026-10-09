"""Seed the dev instance with fictional demo data for screenshots.

Run with: dev/seed_demo.sh
No Gemini call is made: extraction uses a canned reply that matches the
generated demo bill image, so screenshots work without an API key.
"""

import io
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from company.models import Company, SupplierPart
from part.models import Part
from PIL import Image, ImageDraw, ImageFont
from plugin import registry
from stock.models import StockLocation

from bill_scanner import tasks
from bill_scanner.models import Bill, sha256_of
from bill_scanner.services import confirm_bill

SUPPLIER = 'Demo Electronics Supply'
user = get_user_model().objects.get(username='admin')
plugin = registry.get_plugin('bill-scanner')

supplier, _ = Company.objects.get_or_create(
    name=SUPPLIER, defaults={'is_supplier': True, 'currency': 'USD'}
)
location, _ = StockLocation.objects.get_or_create(name='Receiving shelf')

PARTS = [
    ('M3 x 10 hex socket screw', 'SCR-M3-10', 'DES-M3-10'),
    ('LED red 5mm', 'LED-R-5', None),
    ('Resistor 10k 0603', 'RES-10K-0603', 'DES-R10K'),
    ('USB-C cable 1m', 'CBL-USBC-1', None),
    ('Capacitor 100nF 0603', 'CAP-100N-0603', 'DES-C100N'),
]
for name, ipn, sku in PARTS:
    part, _ = Part.objects.get_or_create(
        name=name, defaults={'IPN': ipn, 'purchaseable': True, 'component': True}
    )
    if sku:
        SupplierPart.objects.get_or_create(part=part, supplier=supplier, SKU=sku)


def bill_image(number: str, rows: list[tuple[str, str, str, str]]) -> bytes:
    """Draw a simple fictional invoice as a PNG."""
    image = Image.new('RGB', (900, 640), 'white')
    draw = ImageDraw.Draw(image)
    big = ImageFont.load_default(size=30)
    font = ImageFont.load_default(size=18)
    draw.text((40, 30), SUPPLIER, fill='black', font=big)
    draw.text(
        (40, 75), '12 Example Road, Sampletown  (DEMO DATA)', fill='gray', font=font
    )
    draw.text((620, 30), 'INVOICE', fill='black', font=big)
    draw.text((620, 75), f'No. {number}', fill='black', font=font)
    draw.text((620, 100), 'Date: 2026-10-02', fill='black', font=font)
    y = 170
    for col, x in (('Code', 40), ('Description', 180), ('Qty', 600), ('Unit', 700)):
        draw.text((x, y), col, fill='black', font=font)
    draw.line((40, y + 28, 860, y + 28), fill='black', width=2)
    for code, desc, qty, price in rows:
        y += 45
        for value, x in ((code, 40), (desc, 180), (qty, 600), (price, 700)):
            draw.text((x, y), value, fill='black', font=font)
    draw.line((40, y + 40, 860, y + 40), fill='black', width=1)
    draw.text((600, y + 60), 'Tax 10%   Total $ 41.80', fill='black', font=font)
    buffer = io.BytesIO()
    image.save(buffer, 'PNG')
    return buffer.getvalue()


def demo_bill(number: str, lines: list[dict], read_confidence: list[float]) -> Bill:
    """Create, 'extract' and match one demo bill."""
    rows = [
        (
            line['sku'],
            line['description'],
            str(line['quantity']),
            f'{line["unit_price"]:.2f}',
        )
        for line in lines
    ]
    upload = SimpleUploadedFile(f'{number}.png', bill_image(number, rows), 'image/png')
    file_hash = sha256_of(upload)
    if existing := Bill.objects.filter(file_hash=file_hash).first():
        return existing
    bill = Bill(
        file_name=upload.name,
        content_type='image/png',
        file_hash=file_hash,
        created_by=user,
    )
    bill.file.save(upload.name, upload, save=False)
    bill.save()
    reply = {
        'supplier_name': SUPPLIER,
        'bill_number': number,
        'bill_date': '2026-10-02',
        'currency': 'USD',
        'lines': [
            {**line, 'confidence': conf}
            for line, conf in zip(lines, read_confidence, strict=True)
        ],
    }
    with mock.patch.object(plugin, 'request_extraction', return_value=reply):
        tasks.extract_bill(bill.pk)
    bill.refresh_from_db()
    return bill


# A bill already received, so the list shows a completed entry.
done = demo_bill(
    'DES-2041',
    [
        {
            'sku': 'DES-M3-10',
            'description': 'Hex socket screw M3x10',
            'quantity': 200,
            'unit_price': 0.04,
        },
        {
            'sku': 'DES-C100N',
            'description': 'Capacitor 100nF 0603',
            'quantity': 500,
            'unit_price': 0.01,
        },
    ],
    [0.97, 0.95],
)
if done.status == Bill.Status.REVIEW:
    confirm_bill(done.pk, user, location)

# A bill waiting for review, with mixed confidence.
demo_bill(
    'DES-2057',
    [
        {
            'sku': 'DES-M3-10',
            'description': 'Hex socket screw M3x10',
            'quantity': 100,
            'unit_price': 0.05,
        },
        {
            'sku': 'DES-R10K',
            'description': 'Res 10k 1% 0603',
            'quantity': 250,
            'unit_price': 0.02,
        },
        {
            'sku': '',
            'description': 'Red LED 5 mm diffused',
            'quantity': 50,
            'unit_price': 0.08,
        },
        {
            'sku': 'X-99',
            'description': 'USB C cable 1 metre',
            'quantity': 4,
            'unit_price': 3.10,
        },
        {
            'sku': '',
            'description': 'Packing and handling',
            'quantity': 1,
            'unit_price': 2.50,
        },
    ],
    [0.98, 0.93, 0.88, 0.55, 0.9],
)

print('Demo data ready:', Bill.objects.count(), 'bills')
