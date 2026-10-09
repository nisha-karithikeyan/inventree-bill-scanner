"""Phase 2: building Gemini requests and classifying its responses."""

import base64
import json
from unittest import TestCase

import requests

from bill_scanner.gemini import (
    PermanentGeminiError,
    TransientGeminiError,
    build_request,
    call_with_classification,
    is_google_api_host,
    read_response,
    redact,
    sniff_content_type,
)
from bill_scanner.tests.base import PDF_BYTES, PNG_BYTES, SAMPLE_REPLY


def fake_response(status: int, body) -> requests.Response:
    """A requests.Response carrying the given status and body."""
    response = requests.Response()
    response.status_code = status
    response._content = body if isinstance(body, bytes) else json.dumps(body).encode()
    return response


def gemini_body(text: str, reason: str = 'STOP') -> dict:
    """A generateContent reply with a single text part."""
    return {
        'candidates': [{'content': {'parts': [{'text': text}]}, 'finishReason': reason}]
    }


class SniffTest(TestCase):
    """File types come from magic bytes."""

    def test_known_types(self):
        """PDF, PNG, JPEG, WebP and HEIC are recognised."""
        self.assertEqual(sniff_content_type(PDF_BYTES), 'application/pdf')
        self.assertEqual(sniff_content_type(PNG_BYTES), 'image/png')
        self.assertEqual(sniff_content_type(b'\xff\xd8\xff\xe0abc'), 'image/jpeg')
        self.assertEqual(
            sniff_content_type(b'RIFF\x00\x00\x00\x00WEBPVP8 '), 'image/webp'
        )
        self.assertEqual(sniff_content_type(b'\x00\x00\x00\x18ftypheic'), 'image/heic')
        self.assertEqual(sniff_content_type(b'\x00\x00\x00\x18ftypmif1'), 'image/heif')

    def test_unknown_types(self):
        """Executables and text are rejected even with a friendly name."""
        self.assertIsNone(sniff_content_type(b'MZ\x90\x00'))
        self.assertIsNone(sniff_content_type(b'<html>'))


class BuildRequestTest(TestCase):
    """The request asks for schema-constrained JSON."""

    def test_body(self):
        """Inline data is base64 and the response schema is attached."""
        body = build_request(PNG_BYTES, 'image/png')
        inline = body['contents'][0]['parts'][0]['inline_data']
        self.assertEqual(inline['mime_type'], 'image/png')
        self.assertEqual(base64.b64decode(inline['data']), PNG_BYTES)
        config = body['generationConfig']
        self.assertEqual(config['responseMimeType'], 'application/json')
        self.assertIn('lines', config['responseSchema']['properties'])


class ReadResponseTest(TestCase):
    """Responses become data or a classified error."""

    def test_success(self):
        """A STOP candidate with JSON text is decoded."""
        response = fake_response(200, gemini_body(json.dumps(SAMPLE_REPLY)))
        self.assertEqual(read_response(response), SAMPLE_REPLY)

    def test_split_parts_are_joined(self):
        """JSON split over several parts is reassembled."""
        text = json.dumps(SAMPLE_REPLY)
        body = {
            'candidates': [
                {'content': {'parts': [{'text': text[:10]}, {'text': text[10:]}]}}
            ]
        }
        self.assertEqual(read_response(fake_response(200, body)), SAMPLE_REPLY)

    def test_retryable_status(self):
        """Rate limits and server errors are transient."""
        for status in (429, 500, 503):
            with self.assertRaises(TransientGeminiError):
                read_response(fake_response(status, {'error': {'message': 'busy'}}))

    def test_permanent_status(self):
        """A bad key or bad request will not get better by retrying."""
        for status in (400, 401, 403, 404):
            with self.assertRaises(PermanentGeminiError) as ctx:
                read_response(fake_response(status, {'error': {'message': 'nope'}}))
            self.assertIn('nope', str(ctx.exception))

    def test_error_body_not_json(self):
        """A non-JSON error body still yields a message."""
        with self.assertRaises(PermanentGeminiError) as ctx:
            read_response(fake_response(400, b'Bad things'))
        self.assertIn('Bad things', str(ctx.exception))

    def test_blocked_and_safety(self):
        """Blocked prompts and safety stops are permanent."""
        blocked = {'promptFeedback': {'blockReason': 'SAFETY'}}
        with self.assertRaises(PermanentGeminiError):
            read_response(fake_response(200, blocked))
        with self.assertRaises(PermanentGeminiError):
            read_response(fake_response(200, gemini_body('{}', reason='SAFETY')))

    def test_empty_or_malformed(self):
        """No candidates, a non-JSON body or bad JSON text are transient."""
        with self.assertRaises(TransientGeminiError):
            read_response(fake_response(200, {'candidates': []}))
        with self.assertRaises(TransientGeminiError):
            read_response(fake_response(200, b'<html>'))
        with self.assertRaises(TransientGeminiError):
            read_response(fake_response(200, gemini_body('{"lines": [')))


class CallClassificationTest(TestCase):
    """Network failures are classified too."""

    def test_timeouts_are_transient(self):
        """Timeouts and connection errors can be retried."""
        for error in (requests.Timeout('slow'), requests.ConnectionError('down')):

            def send(error=error):
                raise error

            with self.assertRaises(TransientGeminiError):
                call_with_classification(send)

    def test_other_request_errors_are_permanent(self):
        """Invalid URLs and similar are permanent."""

        def send():
            raise requests.exceptions.InvalidURL('bad')

        with self.assertRaises(PermanentGeminiError):
            call_with_classification(send)

    def test_passthrough(self):
        """A successful call returns the response unchanged."""
        self.assertEqual(call_with_classification(lambda x: x * 2, 21), 42)


class PrivacyHelpersTest(TestCase):
    """The key and bills may only reach Google, and the key is never stored."""

    def test_google_hosts_allowed(self):
        """The default host, regional hosts and bare googleapis.com pass."""
        for value in (
            'generativelanguage.googleapis.com/v1beta',
            'us-central1-aiplatform.googleapis.com/v1',
            'googleapis.com',
        ):
            with self.subTest(value=value):
                self.assertTrue(is_google_api_host(value))

    def test_other_hosts_refused(self):
        """Anything that could send the key elsewhere is refused."""
        for value in (
            '',
            'example.com/v1beta',
            'googleapis.com.evil.example/v1',
            'evilgoogleapis.com/v1',
            'https://generativelanguage.googleapis.com/v1beta',
            'user@generativelanguage.googleapis.com/v1beta',
            'generativelanguage.googleapis.com:8443/v1beta',
            'evil.example/?x=generativelanguage.googleapis.com',
            'evil.example#.googleapis.com',
        ):
            with self.subTest(value=value):
                self.assertFalse(is_google_api_host(value))

    def test_redact(self):
        """Every copy of the secret is masked; an empty secret changes nothing."""
        self.assertEqual(redact('key=abc and abc', 'abc'), 'key=*** and ***')
        self.assertEqual(redact('nothing here', ''), 'nothing here')
