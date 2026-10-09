"""Turning a reviewed bill into a received purchase order."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils.translation import gettext_lazy as _
from djmoney.money import Money

from common.currency import currency_code_default
from common.settings import get_global_setting
from company.models import Company, SupplierPart
from order.models import PurchaseOrder, PurchaseOrderLineItem
from stock.models import StockLocation
from users.models import Owner

from .models import Bill, BillAuditLog, BillLine, normalize_bill_number


class ConfirmError(Exception):
    """The bill cannot be received; the message is shown to the user."""

    def __init__(self, message, duplicate_of: dict | None = None):
        """Keep an optional pointer to the conflicting record."""
        super().__init__(str(message))
        self.duplicate_of = duplicate_of


def find_duplicate(bill: Bill) -> dict | None:
    """Another received bill or purchase order with the same supplier and number."""
    key = normalize_bill_number(bill.bill_number)
    if not key or bill.supplier_id is None:
        return None

    received = (
        Bill.objects.filter(
            supplier_id=bill.supplier_id, bill_key=key, status=Bill.Status.COMPLETED
        )
        .exclude(pk=bill.pk)
        .first()
    )
    if received:
        return {'bill': received.pk, 'purchase_order': received.purchase_order_id}

    for order in (
        PurchaseOrder.objects.filter(supplier_id=bill.supplier_id)
        .exclude(supplier_reference='')
        .only('pk', 'supplier_reference')
    ):
        if normalize_bill_number(order.supplier_reference) == key:
            return {'bill': None, 'purchase_order': order.pk}
    return None


def _supplier_part_for(line: BillLine, supplier: Company) -> SupplierPart:
    """Use the matched supplier part, or create one for this supplier."""
    if line.supplier_part_id and line.supplier_part.supplier_id == supplier.pk:
        return line.supplier_part

    existing = SupplierPart.objects.filter(supplier=supplier, part=line.part)
    if line.sku:
        existing = existing.filter(SKU__iexact=line.sku)
    if found := existing.first():
        return found

    sku = line.sku or f'BILL-{line.part.IPN or line.part.pk}'
    return SupplierPart.objects.create(
        supplier=supplier,
        part=line.part,
        SKU=sku[:100],
        description=line.description[:250],
    )


def _price(line: BillLine, currency: str) -> Money | None:
    if line.unit_price is None:
        return None
    return Money(Decimal(line.unit_price), currency)


@transaction.atomic
def confirm_bill(bill_id: int, user, location: StockLocation | None = None) -> Bill:
    """Create a purchase order for the bill, place it and receive every line.

    Everything happens in one transaction: if any step fails, nothing is kept.
    """
    bill = (
        Bill.objects.select_for_update(of=('self',))
        .select_related('supplier')
        .filter(pk=bill_id)
        .first()
    )
    if bill is None:
        raise ConfirmError(_('Bill not found'))
    if bill.status != Bill.Status.REVIEW:
        raise ConfirmError(_('Only bills that are ready for review can be received'))
    supplier = bill.supplier
    if supplier is None:
        raise ConfirmError(_('Choose the supplier before receiving the bill'))
    if not bill.bill_number.strip():
        raise ConfirmError(_('Enter the bill number before receiving the bill'))
    if duplicate := find_duplicate(bill):
        raise ConfirmError(
            _('This bill has already been received for this supplier'), duplicate
        )

    lines = list(bill.lines.filter(skip=False).select_related('part', 'supplier_part'))
    if not lines:
        raise ConfirmError(_('There are no lines to receive'))
    if missing := [line.line_number for line in lines if line.part_id is None]:
        raise ConfirmError(
            _('Lines without a part: {lines}').format(
                lines=', '.join(map(str, missing))
            )
        )

    currency = bill.currency or supplier.currency or currency_code_default()

    order = PurchaseOrder(
        supplier=supplier,
        supplier_reference=bill.bill_number[:64],
        description=str(_('Scanned bill {number}').format(number=bill.bill_number))[
            :250
        ],
        created_by=user,
        destination=location,
    )
    if get_global_setting('PURCHASEORDER_REQUIRE_RESPONSIBLE', backup_value=False):
        order.responsible = Owner.get_owner(user)
    order.save()

    order_lines = [
        PurchaseOrderLineItem.objects.create(
            order=order,
            part=_supplier_part_for(line, supplier),
            quantity=line.quantity,
            purchase_price=_price(line, currency),
            reference=f'Bill line {line.line_number}'[:100],
        )
        for line in lines
    ]

    order.place_order()
    stock_items = order.receive_line_items(
        location,
        [{'line_item': item, 'quantity': item.quantity} for item in order_lines],
        user,
    )

    bill.status = Bill.Status.COMPLETED
    bill.purchase_order = order
    bill.bill_key = normalize_bill_number(bill.bill_number)
    bill.save(update_fields=['status', 'purchase_order', 'bill_key', 'updated'])

    BillAuditLog.record(
        bill,
        user,
        BillAuditLog.Action.CONFIRMED,
        purchase_order=order.pk,
        purchase_order_reference=order.reference,
        supplier=supplier.pk,
        bill_number=bill.bill_number,
        location=location.pk if location else None,
        currency=currency,
        stock_items=[item.pk for item in stock_items],
        lines=[
            {
                'line': line.line_number,
                'description': line.description,
                'part': line.part_id,
                'supplier_part': item.part_id,
                'quantity': str(line.quantity),
                'unit_price': None if line.unit_price is None else str(line.unit_price),
                'match_method': line.match_method,
                'match_confidence': line.match_confidence,
            }
            for line, item in zip(lines, order_lines, strict=True)
        ],
        skipped=list(
            bill.lines.filter(skip=True).values_list('line_number', flat=True)
        ),
    )
    return bill
