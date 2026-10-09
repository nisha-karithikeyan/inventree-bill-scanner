"""Database models for scanned supplier bills."""

from __future__ import annotations

import hashlib
import re
from typing import IO

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

PURCHASE_ORDER_ROLE = 'purchase_order'


def bill_upload_path(instance: Bill, filename: str) -> str:
    """Store uploads under a plugin-specific media folder."""
    return f'bill_scanner/{instance.file_hash[:2]}/{instance.file_hash}/{filename}'


def normalize_bill_number(number: str) -> str:
    """'INV-001 ' and 'inv 001' are the same bill number."""
    return re.sub(r'[^0-9A-Za-z]', '', number or '').upper()


def sha256_of(stream: IO[bytes]) -> str:
    """Hash a file-like object without loading it all into memory."""
    digest = hashlib.sha256()
    stream.seek(0)
    for chunk in iter(lambda: stream.read(64 * 1024), b''):
        digest.update(chunk)
    stream.seek(0)
    return digest.hexdigest()


class RolePermissionModel(models.Model):
    """Map InvenTree's generic permission checks onto the purchase order role."""

    class Meta:
        """Abstract base."""

        abstract = True

    @classmethod
    def check_user_permission(cls, user, permission: str) -> bool:
        """Grant access to users holding the matching purchase order permission."""
        from users.permissions import check_user_role

        return check_user_role(user, PURCHASE_ORDER_ROLE, permission)


class Bill(RolePermissionModel):
    """An uploaded supplier bill and everything extracted from it."""

    class Status(models.TextChoices):
        """Lifecycle of a bill."""

        PENDING = 'pending', _('Waiting for extraction')
        PROCESSING = 'processing', _('Extracting')
        RETRY = 'retry', _('Waiting to retry')
        FAILED = 'failed', _('Extraction failed')
        REVIEW = 'review', _('Ready for review')
        COMPLETED = 'completed', _('Purchase order created')

    file = models.FileField(upload_to=bill_upload_path, verbose_name=_('File'))
    file_name = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=100)
    # One bill per file: re-uploading the same bytes is refused.
    file_hash = models.CharField(max_length=64, unique=True)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    extracted = models.JSONField(null=True, blank=True)

    supplier_name = models.CharField(max_length=255, blank=True)
    bill_number = models.CharField(max_length=100, blank=True, db_index=True)
    # Normalised bill number, set when the bill is received (duplicate guard).
    bill_key = models.CharField(max_length=100, blank=True, editable=False)
    bill_date = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=3, blank=True)

    supplier = models.ForeignKey(
        'company.Company',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    supplier_confidence = models.FloatField(default=0)

    purchase_order = models.ForeignKey(
        'order.PurchaseOrder',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options."""

        ordering = ['-created']
        verbose_name = _('Scanned Bill')
        constraints = [
            models.UniqueConstraint(
                fields=['supplier', 'bill_key'],
                condition=models.Q(status='completed'),
                name='bill_scanner_unique_received_bill',
            )
        ]

    def __str__(self) -> str:
        """Readable name for admin and logs."""
        label = self.bill_number or self.file_name or f'#{self.pk}'
        return f'{self.supplier_name or _("Unknown supplier")} - {label}'


class BillLine(RolePermissionModel):
    """One line item extracted from a bill, plus its matched part."""

    class MatchMethod(models.TextChoices):
        """How the part match was found."""

        NONE = '', _('No match')
        SUPPLIER_SKU = 'supplier_sku', _('Supplier SKU')
        SKU = 'sku', _('SKU of another supplier')
        MPN = 'mpn', _('Manufacturer part number')
        IPN = 'ipn', _('Internal part number')
        NAME = 'name', _('Fuzzy name match')
        MANUAL = 'manual', _('Chosen by user')

    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name='lines')
    line_number = models.PositiveIntegerField()

    description = models.CharField(max_length=500, blank=True)
    sku = models.CharField(max_length=100, blank=True)
    quantity = models.DecimalField(max_digits=15, decimal_places=5, default=0)
    unit_price = models.DecimalField(
        max_digits=19, decimal_places=6, null=True, blank=True
    )
    confidence = models.FloatField(default=0)

    part = models.ForeignKey(
        'part.Part', on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    supplier_part = models.ForeignKey(
        'company.SupplierPart',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    match_method = models.CharField(
        max_length=20, choices=MatchMethod.choices, default=MatchMethod.NONE, blank=True
    )
    match_confidence = models.FloatField(default=0)

    skip = models.BooleanField(default=False)

    class Meta:
        """Model options."""

        ordering = ['bill', 'line_number']
        unique_together = [('bill', 'line_number')]

    def __str__(self) -> str:
        """Readable name for admin and logs."""
        return f'{self.bill_id}:{self.line_number} {self.description}'


class BillAuditLog(RolePermissionModel):
    """Who did what to a bill. Rows outlive the bill they describe."""

    class Action(models.TextChoices):
        """Recorded actions."""

        UPLOADED = 'uploaded', _('Uploaded')
        EDITED = 'edited', _('Edited')
        LINE_EDITED = 'line_edited', _('Line edited')
        CONFIRMED = 'confirmed', _('Confirmed and received')
        DELETED = 'deleted', _('Deleted')

    bill = models.ForeignKey(
        Bill, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit'
    )
    bill_label = models.CharField(max_length=300)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    details = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        """Model options."""

        ordering = ['-timestamp']

    def __str__(self) -> str:
        """Readable summary."""
        when = f'{self.timestamp:%Y-%m-%d %H:%M}'
        return f'{when} {self.user} {self.action} {self.bill_label}'

    @classmethod
    def record(cls, bill: Bill, user, action: str, **details) -> BillAuditLog:
        """Write one audit entry."""
        return cls.objects.create(
            bill=bill,
            bill_label=str(bill)[:300],
            user=user,
            action=action,
            details=details,
        )
