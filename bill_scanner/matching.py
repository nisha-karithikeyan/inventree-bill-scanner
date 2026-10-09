"""Match extracted bill lines to InvenTree suppliers and parts.

Codes are tried first, most specific to least:

1. SKU of a supplier part from this bill's supplier
2. SKU of a supplier part from any supplier
3. Manufacturer part number (MPN)
4. Internal part number (IPN)

If no code matches, the line description is fuzzy-matched against part names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cached_property

from django.db import transaction

from company.models import Company, ManufacturerPart, SupplierPart
from part.models import Part
from rapidfuzz import fuzz, process, utils

from .models import Bill, BillLine

Method = BillLine.MatchMethod

CONFIDENCE = {
    Method.SUPPLIER_SKU: 1.0,
    Method.MPN: 0.92,
    Method.IPN: 0.92,
    Method.SKU: 0.85,
}
# Codes found inside the description are slightly less trustworthy.
EMBEDDED_CODE_FACTOR = 0.95
NAME_CEILING = 0.9
SAME_SUPPLIER_BONUS = 0.05

_LEGAL_SUFFIXES = re.compile(
    r'\b(ltd|limited|inc|incorporated|llc|gmbh|ag|co|corp|corporation|'
    r'pvt|private|plc|bv|sa|srl|company|the)\b\.?',
    re.IGNORECASE,
)
_CODE_TOKEN = re.compile(r'[A-Za-z0-9][A-Za-z0-9\-_./]{2,}')


def normalize_code(code: str) -> str:
    """Compare codes ignoring case, spaces and punctuation."""
    return re.sub(r'[^0-9A-Za-z]', '', code or '').upper()


def normalize_company(name: str) -> str:
    """Strip legal suffixes so 'Acme Ltd' matches 'ACME Limited'."""
    return ' '.join(_LEGAL_SUFFIXES.sub(' ', utils.default_process(name)).split())


def code_candidates(sku: str, description: str) -> list[tuple[str, float]]:
    """The printed SKU first, then code-like tokens from the description."""
    found = [(sku, 1.0)] if normalize_code(sku) else []
    for token in _CODE_TOKEN.findall(description or ''):
        if any(c.isdigit() for c in token) and any(c.isalpha() for c in token):
            if normalize_code(token) not in {normalize_code(c) for c, _ in found}:
                found.append((token, EMBEDDED_CODE_FACTOR))
    return found


@dataclass(frozen=True)
class PartMatch:
    """The best part found for one line."""

    part_id: int | None = None
    supplier_part_id: int | None = None
    method: str = Method.NONE
    confidence: float = 0.0


NO_MATCH = PartMatch()


def match_supplier(name: str, min_score: int = 80) -> tuple[Company | None, float]:
    """Find the supplier company whose name best matches the bill header."""
    wanted = normalize_company(name)
    if not wanted:
        return None, 0.0
    choices = {
        company.pk: normalize_company(company.name)
        for company in Company.objects.filter(is_supplier=True, active=True)
    }
    best = process.extractOne(
        wanted, choices, scorer=fuzz.token_sort_ratio, score_cutoff=min_score
    )
    if best is None:
        return None, 0.0
    _, score, pk = best
    return Company.objects.get(pk=pk), round(score / 100, 3)


class PartMatcher:
    """Matches many lines for one supplier, caching lookups between lines."""

    def __init__(self, supplier: Company | None, min_name_score: int = 70):
        """Prepare a matcher for lines from one supplier."""
        self.supplier = supplier
        self.min_name_score = min_name_score

    @cached_property
    def supplier_skus(self) -> dict[str, SupplierPart]:
        """This supplier's parts keyed by normalized SKU."""
        if self.supplier is None:
            return {}
        parts = SupplierPart.objects.filter(supplier=self.supplier, part__active=True)
        return {normalize_code(sp.SKU): sp for sp in parts if sp.SKU}

    @cached_property
    def part_names(self) -> dict[int, str]:
        """Active purchaseable parts, for fuzzy name matching."""
        rows = Part.objects.filter(active=True, purchaseable=True).values_list(
            'pk', 'name', 'description'
        )
        return {pk: f'{name} {description}'.strip() for pk, name, description in rows}

    @cached_property
    def supplier_part_ids(self) -> set[int]:
        """Parts this supplier already supplies (used to break name ties)."""
        if self.supplier is None:
            return set()
        return set(
            SupplierPart.objects.filter(supplier=self.supplier).values_list(
                'part_id', flat=True
            )
        )

    def supplier_part_for(self, part_id: int) -> int | None:
        """This supplier's supplier part for a part, when there is exactly one."""
        if self.supplier is None:
            return None
        ids = list(
            SupplierPart.objects.filter(
                supplier=self.supplier, part_id=part_id
            ).values_list('pk', flat=True)[:2]
        )
        return ids[0] if len(ids) == 1 else None

    def _part_match(self, part_id: int, method: str, factor: float) -> PartMatch:
        return PartMatch(
            part_id=part_id,
            supplier_part_id=self.supplier_part_for(part_id),
            method=method,
            confidence=round(CONFIDENCE[method] * factor, 3),
        )

    def match_code(self, code: str, factor: float) -> PartMatch | None:
        """Look a single code up as SKU, MPN or IPN."""
        key = normalize_code(code)
        if not key:
            return None

        if supplier_part := self.supplier_skus.get(key):
            return PartMatch(
                part_id=supplier_part.part_id,
                supplier_part_id=supplier_part.pk,
                method=Method.SUPPLIER_SKU,
                confidence=round(CONFIDENCE[Method.SUPPLIER_SKU] * factor, 3),
            )

        lookups = (
            (Method.MPN, ManufacturerPart.objects.filter(MPN__iexact=code)),
            (Method.IPN, Part.objects.filter(IPN__iexact=code)),
            (Method.SKU, SupplierPart.objects.filter(SKU__iexact=code)),
        )
        for method, queryset in lookups:
            field = 'pk' if method == Method.IPN else 'part_id'
            part_ids = set(
                queryset.filter(
                    **{'active': True}
                    if method == Method.IPN
                    else {'part__active': True}
                ).values_list(field, flat=True)[:5]
            )
            if len(part_ids) == 1:
                return self._part_match(part_ids.pop(), method, factor)
        return None

    def match_name(self, description: str) -> PartMatch:
        """Fuzzy-match the description against part names."""
        if not description or not self.part_names:
            return NO_MATCH
        # token_set_ratio, not WRatio: WRatio's partial token-set step scores
        # about 85 whenever any token is shared, even a unit letter like 'm'.
        results = process.extract(
            description,
            self.part_names,
            scorer=fuzz.token_set_ratio,
            processor=utils.default_process,
            score_cutoff=self.min_name_score,
            limit=5,
        )
        if not results:
            return NO_MATCH

        def ranked(item) -> float:
            _, score, pk = item
            bonus = SAME_SUPPLIER_BONUS * 100 if pk in self.supplier_part_ids else 0
            return score + bonus

        _, score, part_id = max(results, key=ranked)
        confidence = score / 100 * NAME_CEILING
        if part_id in self.supplier_part_ids:
            confidence += SAME_SUPPLIER_BONUS
        return PartMatch(
            part_id=part_id,
            supplier_part_id=self.supplier_part_for(part_id),
            method=Method.NAME,
            confidence=round(min(confidence, NAME_CEILING), 3),
        )

    def match(self, sku: str, description: str) -> PartMatch:
        """Best match for one line."""
        for code, factor in code_candidates(sku, description):
            if found := self.match_code(code, factor):
                return found
        return self.match_name(description)


def apply_match(line: BillLine, match: PartMatch) -> None:
    """Copy a match onto a line (without saving)."""
    line.part_id = match.part_id
    line.supplier_part_id = match.supplier_part_id
    line.match_method = match.method
    line.match_confidence = match.confidence


@transaction.atomic
def match_bill(
    bill: Bill, min_name_score: int = 70, detect_supplier: bool = True
) -> None:
    """Match every non-manual line, and the supplier unless one is already set.

    Pass detect_supplier=False after a user edit, so a supplier the user
    deliberately cleared is not guessed back from the bill text.
    """
    if detect_supplier and bill.supplier_id is None and bill.supplier_name:
        bill.supplier, bill.supplier_confidence = match_supplier(bill.supplier_name)
        bill.save(update_fields=['supplier', 'supplier_confidence', 'updated'])

    matcher = PartMatcher(bill.supplier, min_name_score=min_name_score)
    lines = list(bill.lines.exclude(match_method=Method.MANUAL))
    for line in lines:
        apply_match(line, matcher.match(line.sku, line.description))
    BillLine.objects.bulk_update(
        lines, ['part', 'supplier_part', 'match_method', 'match_confidence']
    )
