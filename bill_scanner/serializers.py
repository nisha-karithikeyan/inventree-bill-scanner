"""REST serializers for scanned bills."""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from stock.models import StockLocation

from .gemini import SUPPORTED_TYPES, sniff_content_type
from .models import Bill, BillAuditLog, BillLine


class BillLineSerializer(serializers.ModelSerializer):
    """A line item with its suggested part."""

    part_detail = serializers.SerializerMethodField()

    class Meta:
        """Serializer options."""

        model = BillLine
        fields = [
            'pk',
            'line_number',
            'description',
            'sku',
            'quantity',
            'unit_price',
            'confidence',
            'part',
            'part_detail',
            'supplier_part',
            'match_method',
            'match_confidence',
            'skip',
        ]
        read_only_fields = [
            'pk',
            'line_number',
            'confidence',
            'match_method',
            'match_confidence',
        ]

    def validate(self, attrs):
        """Keep part, supplier part and the bill's supplier consistent."""
        line = self.instance
        part = attrs.get('part', line.part if line else None)
        supplier_part = attrs.get('supplier_part', line.supplier_part if line else None)

        if 'part' in attrs and 'supplier_part' not in attrs:
            # A new part invalidates the old supplier part.
            if supplier_part is not None and supplier_part.part_id != getattr(
                part, 'pk', None
            ):
                attrs['supplier_part'] = supplier_part = None
        if supplier_part is not None:
            if part is None:
                attrs['part'] = part = supplier_part.part
            if supplier_part.part_id != part.pk:
                raise serializers.ValidationError(
                    {'supplier_part': _('Supplier part is for a different part')}
                )
            supplier = line.bill.supplier_id if line else None
            if supplier and supplier_part.supplier_id != supplier:
                raise serializers.ValidationError(
                    {'supplier_part': _('Supplier part belongs to another supplier')}
                )
        if part is not None and not part.purchaseable:
            raise serializers.ValidationError({'part': _('Part is not purchaseable')})
        quantity = attrs.get('quantity')
        if quantity is not None and quantity <= 0:
            raise serializers.ValidationError(
                {'quantity': _('Quantity must be positive')}
            )
        unit_price = attrs.get('unit_price')
        if unit_price is not None and unit_price < 0:
            raise serializers.ValidationError(
                {'unit_price': _('Price cannot be negative')}
            )
        return attrs

    def get_part_detail(self, line: BillLine) -> dict | None:
        """Small summary of the matched part for the review table."""
        part = line.part
        if part is None:
            return None
        return {
            'pk': part.pk,
            'name': part.name,
            'IPN': part.IPN,
            'description': part.description,
            'thumbnail': part.get_thumbnail_url(),
        }


class BillSerializer(serializers.ModelSerializer):
    """A bill with its extracted header and lines."""

    lines = BillLineSerializer(many=True, read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    file_url = serializers.SerializerMethodField()
    supplier_detail = serializers.SerializerMethodField()
    created_by = serializers.CharField(
        source='created_by.username', read_only=True, default=None
    )

    class Meta:
        """Serializer options."""

        model = Bill
        fields = [
            'pk',
            'file_url',
            'file_name',
            'content_type',
            'status',
            'status_label',
            'attempts',
            'error',
            'supplier_name',
            'bill_number',
            'bill_date',
            'currency',
            'supplier',
            'supplier_detail',
            'supplier_confidence',
            'purchase_order',
            'created_by',
            'created',
            'updated',
            'lines',
        ]
        read_only_fields = [
            'pk',
            'file_name',
            'content_type',
            'status',
            'extracted',
            'attempts',
            'error',
            'supplier_name',
            'supplier_confidence',
            'purchase_order',
            'created_by',
            'created',
            'updated',
        ]

    def validate_supplier(self, supplier):
        """Only supplier companies can be chosen."""
        if supplier is not None and not supplier.is_supplier:
            raise serializers.ValidationError(_('Company is not a supplier'))
        return supplier

    def validate_currency(self, currency: str) -> str:
        """Three-letter ISO code, or blank."""
        currency = (currency or '').strip().upper()
        if currency and (len(currency) != 3 or not currency.isalpha()):
            raise serializers.ValidationError(_('Use a three-letter currency code'))
        return currency

    def get_file_url(self, bill: Bill) -> str | None:
        """URL of the uploaded file (served by InvenTree's media handler)."""
        return bill.file.url if bill.file else None

    def get_supplier_detail(self, bill: Bill) -> dict | None:
        """Name of the linked supplier company."""
        if bill.supplier is None:
            return None
        return {'pk': bill.supplier.pk, 'name': bill.supplier.name}


class BillUploadSerializer(serializers.Serializer):
    """Validate an uploaded bill file."""

    file = serializers.FileField()

    def validate_file(self, upload):
        """Check the size and the real file type (from its bytes)."""
        max_mb = int(self.context.get('max_upload_mb', 15))
        if upload.size > max_mb * 1024 * 1024:
            raise serializers.ValidationError(
                _('File is larger than {size} MB').format(size=max_mb)
            )

        upload.seek(0)
        content_type = sniff_content_type(upload.read(16))
        upload.seek(0)
        if content_type not in SUPPORTED_TYPES:
            raise serializers.ValidationError(
                _('Upload a PDF, JPEG, PNG, WebP or HEIC file')
            )
        upload.detected_type = content_type
        return upload


class BillConfirmSerializer(serializers.Serializer):
    """Options for receiving a bill."""

    location = serializers.PrimaryKeyRelatedField(
        queryset=StockLocation.objects.all(), required=False, allow_null=True
    )


class BillAuditLogSerializer(serializers.ModelSerializer):
    """One audit entry."""

    user = serializers.CharField(source='user.username', read_only=True, default=None)

    class Meta:
        """Serializer options."""

        model = BillAuditLog
        fields = ['pk', 'timestamp', 'user', 'action', 'bill_label', 'details']
