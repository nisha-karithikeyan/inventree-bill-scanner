"""Talking to the Gemini generateContent API.

HTTP itself is done by the plugin's APICallMixin; this module builds the
request, sniffs file types and turns responses or failures into results.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import requests

from .extraction import PROMPT, RESPONSE_SCHEMA

SUPPORTED_TYPES = {
    'application/pdf',
    'image/jpeg',
    'image/png',
    'image/webp',
    'image/heic',
    'image/heif',
}

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

# A pinned model, not an alias such as gemini-flash-latest, so results do not
# change silently. Google retires models, so check this before each release.
DEFAULT_MODEL = 'gemini-3.8-flash'

# The HTTP call runs inside a django-q task, which is killed when its time
# limit runs out. InvenTree caps a per-task limit at 30 s below its broker
# retry interval (300 s by default), so 270 s; the call plus a margin must fit.
TASK_TIMEOUT_MARGIN = 30
MAX_REQUEST_TIMEOUT = 240

# The API key and the bill travel to this host, so only Google may receive them.
GOOGLE_API_DOMAIN = 'googleapis.com'


class GeminiError(Exception):
    """Base error for a failed extraction call."""

    retryable = False


class TransientGeminiError(GeminiError):
    """The call may succeed if tried again later."""

    retryable = True


class PermanentGeminiError(GeminiError):
    """Retrying will not help (bad key, rejected file, blocked content)."""


def is_google_api_host(value: str) -> bool:
    """True for 'host/path' values whose host is googleapis.com or a subdomain.

    Schemes, credentials, ports, queries and fragments are refused, so the
    value cannot smuggle in another destination.
    """
    value = str(value or '').strip()
    if not value or any(mark in value for mark in ('://', '@', '?', '#', '\\', ' ')):
        return False
    host = value.split('/', 1)[0].lower()
    if ':' in host:
        return False
    return host == GOOGLE_API_DOMAIN or host.endswith(f'.{GOOGLE_API_DOMAIN}')


def redact(text: str, secret: str) -> str:
    """Remove a secret from text that may be stored or logged."""
    return text.replace(secret, '***') if secret else text


def sniff_content_type(head: bytes) -> str | None:
    """Detect the file type from its first bytes rather than trusting the client."""
    if head.startswith(b'%PDF-'):
        return 'application/pdf'
    if head.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'image/webp'
    if head[4:8] == b'ftyp':
        brand = head[8:12]
        if brand in (b'heic', b'heix', b'hevc', b'hevx'):
            return 'image/heic'
        if brand in (b'mif1', b'msf1', b'heif'):
            return 'image/heif'
    return None


def build_request(content: bytes, content_type: str) -> dict[str, Any]:
    """Build a generateContent body asking for JSON matching our schema."""
    return {
        'contents': [
            {
                'role': 'user',
                'parts': [
                    {
                        'inline_data': {
                            'mime_type': content_type,
                            'data': base64.b64encode(content).decode('ascii'),
                        }
                    },
                    {'text': PROMPT},
                ],
            }
        ],
        'generationConfig': {
            'temperature': 0,
            'responseMimeType': 'application/json',
            'responseSchema': RESPONSE_SCHEMA,
        },
    }


def _error_message(response: requests.Response) -> str:
    try:
        return str(response.json()['error']['message'])
    except (ValueError, KeyError, TypeError):
        return response.text[:300]


def read_response(response: requests.Response) -> Any:
    """Return the decoded JSON payload, or raise a classified GeminiError."""
    if response.status_code in RETRYABLE_STATUS:
        raise TransientGeminiError(
            f'Gemini returned HTTP {response.status_code}: {_error_message(response)}'
        )
    if response.status_code == 404:
        # Almost always a model name that does not exist or has been retired.
        raise PermanentGeminiError(
            f'Gemini returned HTTP 404: {_error_message(response)} '
            '(Check the Gemini Model setting of the Bill Scanner plugin.)'
        )
    if response.status_code != 200:
        raise PermanentGeminiError(
            f'Gemini returned HTTP {response.status_code}: {_error_message(response)}'
        )

    try:
        body = response.json()
    except ValueError as exc:
        raise TransientGeminiError('Gemini returned a non-JSON response') from exc

    if block := (body.get('promptFeedback') or {}).get('blockReason'):
        raise PermanentGeminiError(f'Gemini blocked the request: {block}')

    candidates = body.get('candidates') or []
    if not candidates:
        raise TransientGeminiError('Gemini returned no candidates')

    candidate = candidates[0]
    reason = candidate.get('finishReason', 'STOP')
    if reason not in ('STOP', 'MAX_TOKENS'):
        raise PermanentGeminiError(f'Gemini stopped early: {reason}')

    parts = (candidate.get('content') or {}).get('parts') or []
    text = ''.join(part.get('text', '') for part in parts)
    try:
        return json.loads(text)
    except ValueError as exc:
        raise TransientGeminiError('Gemini returned malformed JSON') from exc


def call_with_classification(send, *args, **kwargs) -> requests.Response:
    """Run an HTTP call, mapping network failures to transient errors."""
    try:
        return send(*args, **kwargs)
    except (requests.Timeout, requests.ConnectionError) as exc:
        raise TransientGeminiError(f'Could not reach Gemini: {exc}') from exc
    except requests.RequestException as exc:
        raise PermanentGeminiError(f'Gemini request failed: {exc}') from exc
