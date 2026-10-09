"""Compare what the plugin extracted from a bill with hand-written ground truth.

Pure Python on purpose: the judge does not reuse the plugin's own parsing or
normalisation, so a bug there cannot hide itself in the score.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from rapidfuzz import fuzz, utils

HEADER_FIELDS = ('supplier_name', 'bill_number', 'bill_date', 'currency')
DESCRIPTION_MIN = 85  # rapidfuzz WRatio, 0-100
SUPPLIER_NAME_MIN = 90
PAIR_MIN = 50
PRICE_ABS_TOLERANCE = Decimal('0.01')
PRICE_REL_TOLERANCE = Decimal('0.005')

_LEGAL = re.compile(
    r'\b(ltd|limited|inc|llc|gmbh|ag|co|corp|pvt|private|plc|bv|sa|srl|the)\b'
)


def _company(name: Any) -> str:
    return ' '.join(_LEGAL.sub(' ', utils.default_process(str(name or ''))).split())


def _code(value: Any) -> str:
    return re.sub(r'[^0-9A-Za-z]', '', str(value or '')).upper()


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == '':
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _similar(a: Any, b: Any) -> float:
    return fuzz.WRatio(str(a or ''), str(b or ''), processor=utils.default_process)


def price_matches(truth: Any, got: Any) -> bool:
    """Unit prices agree within half a percent or one cent."""
    want, have = _decimal(truth), _decimal(got)
    if want is None or have is None:
        return want is None and have is None
    return abs(want - have) <= max(PRICE_ABS_TOLERANCE, abs(want) * PRICE_REL_TOLERANCE)


def compare_header(field_name: str, truth: Any, got: Any) -> bool:
    """Is one extracted header field correct?"""
    if field_name == 'supplier_name':
        return (
            fuzz.token_sort_ratio(_company(truth), _company(got)) >= SUPPLIER_NAME_MIN
        )
    if field_name == 'bill_number':
        return _code(truth) == _code(got)
    if field_name == 'currency':
        return str(truth or '').upper() == str(got or '').upper()
    return (truth or None) == (got or None)  # bill_date as YYYY-MM-DD


def part_matches(expected: str | None, part: dict | None) -> bool:
    """Expected part is given by IPN or exact name; None means 'no part'."""
    if expected is None:
        return part is None
    if part is None:
        return False
    wanted = expected.strip().casefold()
    return wanted in {
        str(part.get('IPN') or '').casefold(),
        str(part.get('name') or '').casefold(),
    }


def pair_lines(truth: list[dict], got: list[dict]) -> list[tuple[int, int]]:
    """Pair truth lines with extracted lines, best description/SKU match first."""
    candidates = []
    for t, want in enumerate(truth):
        for g, have in enumerate(got):
            score = _similar(want.get('description'), have.get('description'))
            same_sku = bool(_code(want.get('sku'))) and _code(want.get('sku')) == _code(
                have.get('sku')
            )
            if score < PAIR_MIN and not same_sku:
                continue
            if same_sku:
                score += 30
            if _decimal(want.get('quantity')) == _decimal(have.get('quantity')):
                score += 10
            candidates.append((score, t, g))

    pairs, used_t, used_g = [], set(), set()
    for _, t, g in sorted(candidates, key=lambda c: (-c[0], c[1], c[2])):
        if t not in used_t and g not in used_g:
            pairs.append((t, g))
            used_t.add(t)
            used_g.add(g)
    return sorted(pairs)


@dataclass
class LineResult:
    """How one ground-truth line came out."""

    truth: dict
    got: dict | None
    description_ok: bool = False
    quantity_ok: bool = False
    price_ok: bool = False
    match_ok: bool | None = None  # None: truth gives no expected part
    reasons: list[str] = field(default_factory=list)

    @property
    def line_ok(self) -> bool:
        """Description, quantity and unit price all correct."""
        return self.description_ok and self.quantity_ok and self.price_ok

    @property
    def ok(self) -> bool:
        """Line read correctly and, where expected, matched to the right part."""
        return self.line_ok and self.match_ok is not False


@dataclass
class BillResult:
    """How one bill came out."""

    name: str
    status: str
    error: str = ''
    attempts: int = 0
    seconds: float = 0.0
    fields: dict[str, bool] = field(default_factory=dict)
    supplier_ok: bool | None = None
    lines: list[LineResult] = field(default_factory=list)
    extra_lines: list[dict] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def extracted(self) -> bool:
        """Did extraction reach the review stage?"""
        return self.status == 'review'


def score_bill(name: str, truth: dict, got: dict) -> BillResult:
    """Score one bill. `got` is the snapshot written by run_eval.py."""
    result = BillResult(
        name=name,
        status=got.get('status', ''),
        error=got.get('error', ''),
        attempts=got.get('attempts', 0),
        seconds=got.get('seconds', 0.0),
    )
    if not result.extracted:
        result.reasons.append(f'extraction ended as {result.status}: {result.error}')

    for key in HEADER_FIELDS:
        if key not in truth:
            continue
        ok = result.extracted and compare_header(key, truth[key], got.get(key))
        result.fields[key] = ok
        if result.extracted and not ok:
            result.reasons.append(
                f'{key}: expected {truth[key]!r}, got {got.get(key)!r}'
            )

    if 'expected_supplier' in truth:
        want = truth['expected_supplier']
        have = got.get('supplier')
        result.supplier_ok = result.extracted and (
            (want or '').casefold() == (have or '').casefold()
        )
        if result.extracted and not result.supplier_ok:
            result.reasons.append(f'supplier match: expected {want!r}, got {have!r}')

    truth_lines = truth.get('lines', [])
    got_lines = got.get('lines', []) if result.extracted else []
    pairs = dict(pair_lines(truth_lines, got_lines))

    for t, want in enumerate(truth_lines, start=1):
        g = pairs.get(t - 1)
        line = LineResult(truth=want, got=None if g is None else got_lines[g])
        label = f'line {t} ({want.get("description", "")!r})'
        if 'expected_part' in want:
            line.match_ok = False
        if line.got is None:
            if result.extracted:
                line.reasons.append(f'{label}: not extracted')
        else:
            have = line.got
            line.description_ok = (
                _similar(want.get('description'), have.get('description'))
                >= DESCRIPTION_MIN
            )
            line.quantity_ok = _decimal(want.get('quantity')) == _decimal(
                have.get('quantity')
            )
            line.price_ok = price_matches(
                want.get('unit_price'), have.get('unit_price')
            )
            if not line.description_ok:
                line.reasons.append(
                    f'{label}: description read as {have.get("description")!r}'
                )
            if not line.quantity_ok:
                line.reasons.append(
                    f'{label}: quantity {want.get("quantity")} read as '
                    f'{have.get("quantity")}'
                )
            if not line.price_ok:
                line.reasons.append(
                    f'{label}: unit price {want.get("unit_price")} read as '
                    f'{have.get("unit_price")}'
                )
            if 'expected_part' in want:
                line.match_ok = part_matches(want['expected_part'], have.get('part'))
                if not line.match_ok:
                    part = have.get('part') or {}
                    found = part.get('IPN') or part.get('name') or 'no part'
                    line.reasons.append(
                        f'{label}: matched {found!r} by '
                        f'{have.get("match_method") or "-"}, '
                        f'expected {want["expected_part"]!r}'
                    )
        result.lines.append(line)
        result.reasons.extend(line.reasons)

    used = set(pairs.values())
    result.extra_lines = [line for i, line in enumerate(got_lines) if i not in used]
    for extra in result.extra_lines:
        result.reasons.append(
            f'extra line not on the bill: {extra.get("description")!r}'
        )
    return result


def _rate(hits: int, total: int) -> float | None:
    return hits / total if total else None


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def flagged(line: dict | None, threshold: float) -> bool:
    """Would the review panel highlight this line? Mirrors confidence.ts."""
    if line is None:
        return True
    return (
        line.get('part') is None
        or float(line.get('confidence') or 0) < threshold
        or float(line.get('match_confidence') or 0) < threshold
    )


def summarise(results: list[BillResult], threshold: float) -> dict[str, Any]:
    """Aggregate numbers for the report."""
    lines = [line for bill in results for line in bill.lines]
    paired = [line for line in lines if line.got is not None]
    matchable = [line for line in lines if line.match_ok is not None]
    extracted_count = sum(len(bill.extra_lines) for bill in results) + len(paired)

    fields = {}
    for key in HEADER_FIELDS:
        values = [bill.fields[key] for bill in results if key in bill.fields]
        fields[key] = (_rate(sum(values), len(values)), len(values))
    supplier = [bill.supplier_ok for bill in results if bill.supplier_ok is not None]

    by_method: dict[str, list[bool]] = {}
    for line in matchable:
        method = (line.got or {}).get('match_method') or 'none'
        by_method.setdefault(method, []).append(bool(line.match_ok))

    wrong = [line for line in lines if not line.ok]
    right = [line for line in lines if line.ok]
    # A correct 'no part' line is meant to be highlighted, so it is no false alarm.
    right_with_part = [line for line in right if (line.got or {}).get('part')]

    return {
        'bills': len(results),
        'extracted': sum(bill.extracted for bill in results),
        'attempts': _mean([bill.attempts for bill in results]),
        'seconds': _mean([bill.seconds for bill in results]),
        'fields': fields,
        'supplier_match': (_rate(sum(supplier), len(supplier)), len(supplier)),
        'truth_lines': len(lines),
        'extracted_lines': extracted_count,
        'line_recall': _rate(len(paired), len(lines)),
        'line_precision': _rate(len(paired), extracted_count),
        'description': _rate(sum(line.description_ok for line in paired), len(paired)),
        'quantity': _rate(sum(line.quantity_ok for line in paired), len(paired)),
        'unit_price': _rate(sum(line.price_ok for line in paired), len(paired)),
        'line_accuracy': _rate(sum(line.line_ok for line in lines), len(lines)),
        'match_accuracy': (
            _rate(sum(bool(line.match_ok) for line in matchable), len(matchable)),
            len(matchable),
        ),
        'match_by_method': {
            method: (_rate(sum(oks), len(oks)), len(oks))
            for method, oks in sorted(by_method.items())
        },
        'read_confidence': _mean([float(line.got['confidence']) for line in paired]),
        'read_confidence_right': _mean(
            [float(line.got['confidence']) for line in right if line.got]
        ),
        'read_confidence_wrong': _mean(
            [float(line.got['confidence']) for line in wrong if line.got]
        ),
        'match_confidence': _mean(
            [float(line.got['match_confidence']) for line in paired]
        ),
        'wrong_lines': len(wrong),
        'wrong_flagged': _rate(
            sum(flagged(line.got, threshold) for line in wrong), len(wrong)
        ),
        'right_flagged': _rate(
            sum(flagged(line.got, threshold) for line in right_with_part),
            len(right_with_part),
        ),
        'threshold': threshold,
    }


def _pct(value: float | None) -> str:
    return '–' if value is None else f'{value * 100:.1f}%'


def _num(value: float | None, digits: int = 2) -> str:
    return '–' if value is None else f'{value:.{digits}f}'


def render_markdown(
    summary: dict[str, Any], results: list[BillResult], meta: dict
) -> str:
    """The report written to eval/results/report.md."""
    s = summary
    out = [
        '# Bill scanner accuracy report',
        '',
        f'- Run: {meta["when"]}',
        f'- Model: `{meta["model"]}`, plugin {meta["version"]}',
        f'- Bills: {s["bills"]}, extracted: {s["extracted"]}, '
        f'average attempts {_num(s["attempts"])}, '
        f'average time {_num(s["seconds"], 1)} s',
        '',
        '## Header fields',
        '',
        '| Field | Accuracy | Bills |',
        '| ----- | -------- | ----- |',
    ]
    for key, (rate, count) in s['fields'].items():
        out.append(f'| {key} | {_pct(rate)} | {count} |')
    rate, count = s['supplier_match']
    out.append(f'| supplier matched to company | {_pct(rate)} | {count} |')

    out += [
        '',
        '## Line items',
        '',
        f'- Ground-truth lines: {s["truth_lines"]}, extracted lines: '
        f'{s["extracted_lines"]}',
        f'- Recall (truth lines found): {_pct(s["line_recall"])}',
        f'- Precision (extracted lines that are real): {_pct(s["line_precision"])}',
        f'- Description correct: {_pct(s["description"])} of found lines',
        f'- Quantity correct: {_pct(s["quantity"])} of found lines',
        f'- Unit price correct: {_pct(s["unit_price"])} of found lines',
        f'- **Line fully correct: {_pct(s["line_accuracy"])}** of all truth lines',
        '',
        '## Part matching',
        '',
        f'- **Accuracy: {_pct(s["match_accuracy"][0])}** of '
        f'{s["match_accuracy"][1]} lines with an expected part',
        '',
        '| Method used | Correct | Lines |',
        '| ----------- | ------- | ----- |',
    ]
    for method, (rate, count) in s['match_by_method'].items():
        out.append(f'| {method} | {_pct(rate)} | {count} |')

    out += [
        '',
        '## Confidence',
        '',
        f'- Average read confidence (Gemini): {_num(s["read_confidence"])}',
        f'  - on correct lines: {_num(s["read_confidence_right"])}, '
        f'on wrong lines: {_num(s["read_confidence_wrong"])}',
        f'- Average match confidence: {_num(s["match_confidence"])}',
        f'- Wrong lines highlighted for review (threshold {s["threshold"]:.2f}): '
        f'{_pct(s["wrong_flagged"])} of {s["wrong_lines"]}',
        f'- Correctly matched lines highlighted anyway (false alarms): '
        f'{_pct(s["right_flagged"])}',
        '',
        '## Failures',
        '',
    ]
    failures = [bill for bill in results if bill.reasons]
    if not failures:
        out.append('None.')
    for bill in failures:
        out.append(f'### {bill.name}')
        out.append('')
        out += [f'- {reason}' for reason in bill.reasons]
        out.append('')
    return '\n'.join(out).rstrip() + '\n'
