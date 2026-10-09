"""Plugin entry point for InvenTree."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.urls import path
from django.utils.translation import gettext_lazy as _

from plugin import InvenTreePlugin
from plugin.mixins import (
    APICallMixin,
    AppMixin,
    ScheduleMixin,
    SettingsMixin,
    UrlsMixin,
    UserInterfaceMixin,
)

from . import PLUGIN_VERSION
from .gemini import DEFAULT_MODEL, MAX_REQUEST_TIMEOUT, is_google_api_host


def validate_api_host(value: str) -> None:
    """Setting validator: the key and bills may only go to Google."""
    if not is_google_api_host(value):
        raise ValidationError(
            _('Enter a googleapis.com host and path, without https://')
        )


def lazy_view(name: str):
    """Return a view that imports the real DRF view on first use.

    InvenTree builds plugin URLs before AppMixin has registered this app, so
    the views (which import our models) cannot be imported at that point.
    """
    cache: dict[str, Any] = {}

    def view(request, *args, **kwargs):
        if name not in cache:
            from . import api

            cache[name] = getattr(api, name).as_view()
        return cache[name](request, *args, **kwargs)

    # DRF views are CSRF-exempt at the Django layer and enforce CSRF for
    # session auth themselves; mirror that on the wrapper.
    view.csrf_exempt = True  # type: ignore[attr-defined]
    view.__name__ = name
    return view


class BillScannerPlugin(
    AppMixin,
    APICallMixin,
    ScheduleMixin,
    SettingsMixin,
    UrlsMixin,
    UserInterfaceMixin,
    InvenTreePlugin,
):
    """Extract supplier bills with Gemini Vision and create purchase orders."""

    NAME = 'BillScanner'
    SLUG = 'bill-scanner'
    TITLE = _('Bill Scanner')
    DESCRIPTION = _(
        'Upload a supplier bill, extract it with Gemini Vision, review the '
        'matched parts and receive it as a purchase order.'
    )
    AUTHOR = 'Nisha Karthikeyan'
    VERSION = PLUGIN_VERSION
    LICENSE = 'MIT'
    MIN_VERSION = '1.0.0'

    API_URL_SETTING = 'GEMINI_API_URL'
    API_TOKEN_SETTING = 'GEMINI_API_KEY'

    SETTINGS = {
        'GEMINI_API_KEY': {
            'name': _('Gemini API Key'),
            'description': _('API key used to call Google Gemini Vision'),
            'default': '',
            'protected': True,
            'required': True,
        },
        'GEMINI_MODEL': {
            'name': _('Gemini Model'),
            'description': _('Gemini model name, for example {model}').format(
                model=DEFAULT_MODEL
            ),
            'default': DEFAULT_MODEL,
        },
        'GEMINI_API_URL': {
            'name': _('Gemini API Host'),
            'description': _('Host and version path of the Gemini REST API'),
            'default': 'generativelanguage.googleapis.com/v1beta',
            'validator': validate_api_host,
        },
        'REQUEST_TIMEOUT': {
            'name': _('Request Timeout'),
            'description': _('Seconds to wait for Gemini before giving up'),
            'default': 120,
            'units': 's',
            'validator': [
                int,
                MinValueValidator(10),
                MaxValueValidator(MAX_REQUEST_TIMEOUT),
            ],
        },
        'MAX_ATTEMPTS': {
            'name': _('Maximum Attempts'),
            'description': _('How often a failed extraction is tried in total'),
            'default': 3,
            'validator': [int, MinValueValidator(1), MaxValueValidator(10)],
        },
        'MAX_UPLOAD_MB': {
            'name': _('Maximum Upload Size'),
            'description': _('Largest bill file accepted for upload'),
            'default': 15,
            'units': 'MB',
            'validator': [int, MinValueValidator(1), MaxValueValidator(20)],
        },
        'MATCH_MIN_SCORE': {
            'name': _('Minimum Name Match Score'),
            'description': _(
                'Fuzzy name matches scoring below this (0-100) are ignored'
            ),
            'default': 70,
            'validator': [int, MinValueValidator(0), MaxValueValidator(100)],
        },
        'LOW_CONFIDENCE': {
            'name': _('Low Confidence Threshold'),
            'description': _('Lines below this confidence (0-100) are highlighted'),
            'default': 75,
            'validator': [int, MinValueValidator(0), MaxValueValidator(100)],
        },
    }

    SCHEDULED_TASKS = {
        'retry_bills': {
            'func': 'bill_scanner.tasks.retry_due_bills',
            'schedule': 'I',
            'minutes': 1,
        }
    }

    def setup_urls(self):
        """Expose the REST API below /plugin/bill-scanner/api/."""
        return [
            path('api/bills/', lazy_view('BillList'), name='bill-list'),
            path('api/bills/<int:pk>/', lazy_view('BillDetail'), name='bill-detail'),
            path(
                'api/bills/<int:pk>/lines/<int:line>/',
                lazy_view('BillLineDetail'),
                name='bill-line-detail',
            ),
            path(
                'api/bills/<int:pk>/confirm/',
                lazy_view('BillConfirm'),
                name='bill-confirm',
            ),
            path(
                'api/bills/<int:pk>/audit/', lazy_view('BillAudit'), name='bill-audit'
            ),
            path(
                'api/bills/<int:pk>/extract/',
                lazy_view('BillExtract'),
                name='bill-extract',
            ),
        ]

    @property
    def api_headers(self) -> dict[str, str]:
        """Gemini authenticates with an x-goog-api-key header, not a bearer token."""
        return {
            'Content-Type': 'application/json',
            'x-goog-api-key': str(self.get_setting('GEMINI_API_KEY') or ''),
        }

    def request_extraction(self, content: bytes, content_type: str) -> Any:
        """Send a bill to Gemini and return the decoded JSON it produced."""
        from .gemini import (
            GeminiError,
            PermanentGeminiError,
            build_request,
            call_with_classification,
            read_response,
            redact,
        )

        key = str(self.get_setting('GEMINI_API_KEY') or '')
        if not key:
            raise PermanentGeminiError('The Gemini API key is not configured')
        # Checked again here: the setting may predate the validator.
        if not is_google_api_host(str(self.get_setting('GEMINI_API_URL'))):
            raise PermanentGeminiError(
                'The Gemini API host must be a googleapis.com host'
            )

        model = str(self.get_setting('GEMINI_MODEL') or DEFAULT_MODEL)
        try:
            response = call_with_classification(
                self.api_call,
                f'models/{model}:generateContent',
                method='POST',
                json=build_request(content, content_type),
                simple_response=False,
                timeout=int(self.get_setting('REQUEST_TIMEOUT') or 120),
            )
            return read_response(response)
        except GeminiError as exc:
            # Error text is stored on the bill and logged, so it must never
            # carry the key. 'from None' drops the chained requests error,
            # whose request object holds the key header and the bill.
            raise type(exc)(redact(str(exc), key)) from None

    def get_ui_panels(self, request, context, **kwargs):
        """Show the bill scanner on the Purchasing landing page."""
        from users.permissions import check_user_role

        if (context or {}).get('target_model') != 'purchasing':
            return []
        if not check_user_role(request.user, 'purchase_order', 'view'):
            return []
        return [
            {
                'key': 'bill-scanner',
                'title': _('Scanned Bills'),
                'description': _('Upload supplier bills and receive them as orders'),
                'icon': 'ti:file-invoice:outline',
                'source': self.plugin_static_file(
                    'BillScanner.js:renderBillScannerPanel'
                ),
                'context': self.ui_context(request.user),
            }
        ]

    def ui_context(self, user) -> dict[str, Any]:
        """Settings and permissions the review UI needs."""
        from users.permissions import check_user_role

        return {
            'api': f'/{self.base_url}api',
            'low_confidence': int(self.get_setting('LOW_CONFIDENCE') or 75) / 100,
            'max_upload_mb': int(self.get_setting('MAX_UPLOAD_MB') or 15),
            'has_api_key': bool(self.get_setting('GEMINI_API_KEY')),
            'can_edit': check_user_role(user, 'purchase_order', 'change'),
            'can_confirm': check_user_role(user, 'purchase_order', 'add')
            and check_user_role(user, 'stock', 'add'),
        }
