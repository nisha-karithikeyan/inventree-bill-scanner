"""REST API views, mounted under /plugin/bill-scanner/api/."""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from InvenTree.permissions import RolePermission
from users.permissions import check_user_role

from .matching import match_bill
from .models import PURCHASE_ORDER_ROLE, Bill, BillAuditLog, BillLine, sha256_of
from .serializers import (
    BillAuditLogSerializer,
    BillConfirmSerializer,
    BillLineSerializer,
    BillSerializer,
    BillUploadSerializer,
)
from .services import ConfirmError, confirm_bill
from .tasks import get_plugin, queue_extraction


class BillPermissionMixin:
    """Every endpoint needs the purchase order role (view/add/change/delete)."""

    permission_classes = [IsAuthenticated, RolePermission]
    role_required = PURCHASE_ORDER_ROLE


def bill_queryset():
    """Bills with the related rows the serializers read."""
    return Bill.objects.select_related('supplier', 'created_by').prefetch_related(
        'lines__part'
    )


def audit_changes(serializer) -> dict:
    """JSON-safe copy of the fields a request changed."""
    changes = {}
    for key, value in serializer.validated_data.items():
        if hasattr(value, 'pk'):
            value = value.pk
        elif value is not None and not isinstance(value, bool):
            value = str(value)
        changes[key] = value
    return changes


def ensure_editable(bill: Bill) -> None:
    """Only bills under review can be changed."""
    if bill.status != Bill.Status.REVIEW:
        raise ValidationError(_('Only bills that are ready for review can be edited'))


class BillList(BillPermissionMixin, generics.ListAPIView):
    """List bills (GET) or upload a new one (POST multipart 'file')."""

    serializer_class = BillSerializer
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        """Optionally filter by ?status=."""
        queryset = bill_queryset()
        if wanted := self.request.query_params.get('status'):
            queryset = queryset.filter(status__in=wanted.split(','))
        return queryset

    def post(self, request, *args, **kwargs):
        """Store the file and queue it for extraction."""
        plugin = get_plugin()
        upload_serializer = BillUploadSerializer(
            data=request.data,
            context={'max_upload_mb': plugin.get_setting('MAX_UPLOAD_MB')},
        )
        upload_serializer.is_valid(raise_exception=True)
        upload = upload_serializer.validated_data['file']

        file_hash = sha256_of(upload)
        if existing := Bill.objects.filter(file_hash=file_hash).first():
            return Response(
                {
                    'detail': _('This file has already been uploaded'),
                    'duplicate_of': {'bill': existing.pk},
                },
                status=status.HTTP_409_CONFLICT,
            )

        bill = Bill(
            file_name=upload.name[:255],
            content_type=upload.detected_type,
            file_hash=file_hash,
            created_by=request.user,
        )
        bill.file.save(upload.name, upload, save=False)
        bill.save()
        BillAuditLog.record(
            bill, request.user, BillAuditLog.Action.UPLOADED, file_hash=file_hash
        )
        transaction.on_commit(lambda: queue_extraction(bill))

        return Response(
            BillSerializer(bill, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


class BillDetail(BillPermissionMixin, generics.RetrieveUpdateDestroyAPIView):
    """Read, correct or delete a single bill."""

    serializer_class = BillSerializer
    parser_classes = [JSONParser]

    def get_queryset(self):
        """All bills."""
        return bill_queryset()

    def perform_update(self, serializer):
        """Save header corrections; a new supplier re-runs part matching."""
        bill = serializer.instance
        ensure_editable(bill)
        old_supplier = bill.supplier_id
        bill = serializer.save()
        BillAuditLog.record(
            bill,
            self.request.user,
            BillAuditLog.Action.EDITED,
            changes=audit_changes(serializer),
        )
        if bill.supplier_id != old_supplier:
            bill.supplier_confidence = 1.0 if bill.supplier_id else 0.0
            bill.save(update_fields=['supplier_confidence', 'updated'])
            match_bill(
                bill,
                min_name_score=int(get_plugin().get_setting('MATCH_MIN_SCORE')),
                detect_supplier=False,
            )

    def perform_destroy(self, instance):
        """Keep completed bills as a record of what was received."""
        if instance.status == Bill.Status.COMPLETED:
            raise ValidationError(_('This bill has already been received'))
        BillAuditLog.record(instance, self.request.user, BillAuditLog.Action.DELETED)
        instance.file.delete(save=False)
        instance.delete()


class BillExtract(BillPermissionMixin, APIView):
    """Run extraction again for a failed bill, or re-read one under review."""

    rolemap = {'POST': 'change'}

    def post(self, request, pk: int):
        """Reset the attempt counter and queue the bill."""
        bill = generics.get_object_or_404(Bill, pk=pk)
        if bill.status not in (Bill.Status.FAILED, Bill.Status.REVIEW):
            raise ValidationError(_('This bill cannot be extracted right now'))
        bill.status = Bill.Status.PENDING
        bill.attempts = 0
        bill.error = ''
        bill.save(update_fields=['status', 'attempts', 'error', 'updated'])
        transaction.on_commit(lambda: queue_extraction(bill))
        return Response(
            BillSerializer(bill, context={'request': request}).data,
            status=status.HTTP_202_ACCEPTED,
        )


class BillLineDetail(BillPermissionMixin, generics.RetrieveUpdateAPIView):
    """Correct one line: quantity, price, chosen part or skip flag."""

    serializer_class = BillLineSerializer
    parser_classes = [JSONParser]
    lookup_url_kwarg = 'line'

    def get_queryset(self):
        """Lines of the bill in the URL."""
        return BillLine.objects.filter(bill_id=self.kwargs['pk']).select_related(
            'bill', 'part'
        )

    def perform_update(self, serializer):
        """A part chosen by the user is a manual, fully trusted match."""
        line = serializer.instance
        ensure_editable(line.bill)
        old = (line.part_id, line.supplier_part_id)
        line = serializer.save()
        BillAuditLog.record(
            line.bill,
            self.request.user,
            BillAuditLog.Action.LINE_EDITED,
            line=line.line_number,
            changes=audit_changes(serializer),
        )
        if (line.part_id, line.supplier_part_id) != old:
            line.match_method = (
                BillLine.MatchMethod.MANUAL
                if line.part_id
                else BillLine.MatchMethod.NONE
            )
            line.match_confidence = 1.0 if line.part_id else 0.0
            line.save(update_fields=['match_method', 'match_confidence'])


class BillConfirm(BillPermissionMixin, APIView):
    """Create the purchase order and receive the stock (POST {location})."""

    rolemap = {'POST': 'add'}

    def post(self, request, pk: int):
        """Receive the bill, refusing duplicates."""
        if not check_user_role(request.user, 'stock', 'add'):
            return Response(
                {'detail': _('Receiving stock needs the stock "add" permission')},
                status=status.HTTP_403_FORBIDDEN,
            )
        generics.get_object_or_404(Bill, pk=pk)
        serializer = BillConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            bill = confirm_bill(
                pk, request.user, serializer.validated_data.get('location')
            )
        except ConfirmError as exc:
            body = {'detail': str(exc)}
            if exc.duplicate_of:
                body['duplicate_of'] = exc.duplicate_of
                return Response(body, status=status.HTTP_409_CONFLICT)
            return Response(body, status=status.HTTP_400_BAD_REQUEST)
        except DjangoValidationError as exc:
            return Response(
                {'detail': '; '.join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST
            )
        bill = bill_queryset().get(pk=bill.pk)
        return Response(BillSerializer(bill, context={'request': request}).data)


class BillAudit(BillPermissionMixin, generics.ListAPIView):
    """Audit trail of one bill."""

    serializer_class = BillAuditLogSerializer
    pagination_class = None

    def get_queryset(self):
        """Entries for the bill in the URL, newest first."""
        return BillAuditLog.objects.filter(bill_id=self.kwargs['pk']).select_related(
            'user'
        )
