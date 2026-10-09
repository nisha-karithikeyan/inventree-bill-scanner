"""Run every bill in eval/bills/ through the plugin and score it.

    eval/run.sh              call Gemini for every bill, write eval/results/
    eval/run.sh --check      validate bills and ground truth only (no API call)
    eval/run.sh --only acme  only bills whose file name contains 'acme'

Each bill takes exactly the plugin's own path: BillUploadSerializer validates
the file, then tasks.extract_bill (the function the background worker runs)
calls Gemini, parses the reply, saves the lines and runs match_bill. The
plugin's settings are used as they are, including the API key and the
matching threshold.

Every bill is processed inside a database transaction that is rolled back,
with uploads in a temporary media folder, so nothing is left in InvenTree.
Matching runs against the parts and suppliers in the database you point at.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
BILLS = HERE / 'bills'
RESULTS = HERE / 'results'
FILE_TYPES = {'.pdf', '.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif'}
MAX_RETRY_WAIT = 120  # seconds; the plugin's own backoff is used up to this


class Rollback(Exception):
    """Raised to undo everything a bill wrote to the database."""


def setup_django() -> None:
    """Load InvenTree with the plugin, as manage.py would."""
    backend = Path(os.environ['INVENTREE_SRC']) / 'src' / 'backend' / 'InvenTree'
    sys.path.insert(0, str(backend))
    sys.path.insert(0, str(HERE))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'InvenTree.settings')
    import django

    django.setup()


def find_bills(only: str | None) -> list[tuple[Path, Path]]:
    """(bill file, ground truth file) pairs; truth is <stem>.json next to the bill."""
    pairs = []
    for path in sorted(BILLS.iterdir()):
        if path.suffix.lower() not in FILE_TYPES:
            continue
        if only and only.lower() not in path.name.lower():
            continue
        pairs.append((path, path.with_suffix('.json')))
    return pairs


def check_truth(bill: Path, truth_path: Path) -> list[str]:
    """Problems with one ground-truth file (missing file, fields, unknown parts)."""
    from django.db.models import Q

    from company.models import Company
    from part.models import Part

    if not truth_path.exists():
        return [f'{bill.name}: no ground truth file {truth_path.name}']
    try:
        truth = json.loads(truth_path.read_text())
    except ValueError as exc:
        return [f'{truth_path.name}: invalid JSON ({exc})']

    problems = []
    for key in ('supplier_name', 'bill_number', 'lines'):
        if key not in truth:
            problems.append(f'{truth_path.name}: missing "{key}"')
    for number, line in enumerate(truth.get('lines', []), start=1):
        for key in ('description', 'quantity'):
            if key not in line:
                problems.append(f'{truth_path.name}: line {number} missing "{key}"')
        expected = line.get('expected_part')
        if (
            expected
            and not Part.objects.filter(
                Q(IPN__iexact=expected) | Q(name__iexact=expected)
            ).exists()
        ):
            problems.append(
                f'{truth_path.name}: line {number} expected part {expected!r} '
                'is not in InvenTree (use its IPN or exact name)'
            )
    supplier = truth.get('expected_supplier')
    if supplier and not Company.objects.filter(name__iexact=supplier).exists():
        problems.append(f'{truth_path.name}: supplier {supplier!r} is not in InvenTree')
    return problems


def snapshot(bill) -> dict:
    """What the plugin stored, in the shape scoring.py expects."""
    return {
        'status': bill.status,
        'error': bill.error,
        'attempts': bill.attempts,
        'supplier_name': bill.supplier_name,
        'bill_number': bill.bill_number,
        'bill_date': bill.bill_date.isoformat() if bill.bill_date else None,
        'currency': bill.currency,
        'supplier': bill.supplier.name if bill.supplier else None,
        'supplier_confidence': bill.supplier_confidence,
        'lines': [
            {
                'description': line.description,
                'sku': line.sku,
                'quantity': str(line.quantity.normalize()),
                'unit_price': None
                if line.unit_price is None
                else str(line.unit_price.normalize()),
                'confidence': line.confidence,
                'part': None
                if line.part is None
                else {'pk': line.part.pk, 'IPN': line.part.IPN, 'name': line.part.name},
                'match_method': line.match_method,
                'match_confidence': line.match_confidence,
            }
            for line in bill.lines.select_related('part').order_by('line_number')
        ],
    }


def run_bill(path: Path, plugin) -> dict:
    """Upload, extract and match one bill the way the plugin does, then undo it."""
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.db import transaction

    from bill_scanner import tasks
    from bill_scanner.models import Bill
    from bill_scanner.serializers import BillUploadSerializer

    upload = SimpleUploadedFile(path.name, path.read_bytes())
    serializer = BillUploadSerializer(
        data={'file': upload},
        context={'max_upload_mb': plugin.get_setting('MAX_UPLOAD_MB')},
    )
    if not serializer.is_valid():
        return {
            'status': 'rejected',
            'error': json.dumps(serializer.errors),
            'lines': [],
        }
    upload = serializer.validated_data['file']

    started = time.monotonic()
    result: dict = {}
    try:
        with transaction.atomic():
            bill = Bill(
                file_name=path.name,
                content_type=upload.detected_type,
                # Not the real hash: the file may already be uploaded in this
                # InvenTree, and the row is rolled back anyway.
                file_hash=hashlib.sha256(b'eval:' + upload.read()).hexdigest(),
            )
            upload.seek(0)
            bill.file.save(path.name, upload, save=False)
            bill.save()

            tasks.extract_bill(bill.pk)
            bill.refresh_from_db()
            while bill.status == Bill.Status.RETRY:
                wait = min(
                    tasks.retry_delay(bill.attempts).total_seconds(), MAX_RETRY_WAIT
                )
                print(f'    retrying in {wait:.0f} s: {bill.error}')
                time.sleep(wait)
                tasks.extract_bill(bill.pk)
                bill.refresh_from_db()

            result = snapshot(bill)
            raise Rollback
    except Rollback:
        pass
    result['seconds'] = round(time.monotonic() - started, 1)
    return result


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument(
        '--check', action='store_true', help='validate only, no API call'
    )
    parser.add_argument('--only', help='only bills whose file name contains this text')
    args = parser.parse_args()

    setup_django()
    from django.test import override_settings

    from plugin import registry
    from scoring import render_markdown, score_bill, summarise

    from bill_scanner import PLUGIN_VERSION

    plugin = registry.get_plugin('bill-scanner')
    if plugin is None:
        print('The bill-scanner plugin is not active in this InvenTree.')
        return 1

    pairs = find_bills(args.only)
    if not pairs:
        print(f'No bills found in {BILLS}. See eval/README.md.')
        return 1
    problems = [p for bill, truth in pairs for p in check_truth(bill, truth)]
    for problem in problems:
        print(f'  ! {problem}')
    if problems:
        return 1
    if args.check:
        print(f'{len(pairs)} bill(s) ready. No API call made.')
        return 0
    if not plugin.get_setting('GEMINI_API_KEY'):
        print('Set the Gemini API key in the plugin settings first.')
        return 1

    print(
        f'Sending {len(pairs)} bill(s) to Gemini '
        f'({plugin.get_setting("GEMINI_MODEL")}).'
    )
    media = tempfile.mkdtemp(prefix='bill-scanner-eval-')
    results, raw = [], {}
    try:
        with override_settings(MEDIA_ROOT=media):
            for bill_path, truth_path in pairs:
                print(f'  {bill_path.name}')
                got = run_bill(bill_path, plugin)
                raw[bill_path.name] = got
                truth = json.loads(truth_path.read_text())
                results.append(score_bill(bill_path.name, truth, got))
    finally:
        shutil.rmtree(media, ignore_errors=True)

    threshold = int(plugin.get_setting('LOW_CONFIDENCE') or 75) / 100
    summary = summarise(results, threshold)
    report = render_markdown(
        summary,
        results,
        {
            'when': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'model': plugin.get_setting('GEMINI_MODEL'),
            'version': PLUGIN_VERSION,
        },
    )
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / 'report.md').write_text(report)
    (RESULTS / 'extracted.json').write_text(json.dumps(raw, indent=2, default=str))
    print()
    print(report)
    print(f'Written to {RESULTS / "report.md"}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
