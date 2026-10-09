# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Found during the first real end-to-end test with the Gemini API.

### Fixed

- The default model `gemini-2.5-flash` is no longer available to new API
  keys; the default is now `gemini-3.8-flash`. A 404 from Gemini now says to
  check the *Gemini Model* setting. Existing installs keep their stored model
  setting and may need to change it.
- Slow Gemini replies could exceed InvenTree's 90-second worker time limit.
  The task was killed mid-request and the bill stayed in *Extracting* until
  the 15-minute rescue. The task now gets *Request Timeout* + 30 s, and a
  time-limit kill is retried like any other transient error.

### Changed

- *Request Timeout* is limited to 240 seconds, to fit InvenTree's
  per-task time limit.

## [0.1.0] - 2026-10-09

First public release (beta). Extraction has been tested with mocked Gemini
responses; real-world accuracy has not been measured yet.

### Added

- **Upload** photos or PDFs of supplier bills (PDF, JPEG, PNG, WebP,
  HEIC/HEIF) from a *Scanned Bills* panel on InvenTree's Purchasing page. The
  file type is detected from its bytes, and the size limit is configurable.
- **Extraction with Google Gemini** in a django-q2 background task, using a JSON
  response schema. It reads supplier, bill number, date, currency, and lines
  with description, SKU, quantity, unit price and a confidence score.
  Numbers, dates and confidence values are validated and normalised.
- **Retries:** transient failures (timeouts, rate limits, 5xx, malformed
  replies) are retried with exponential backoff up to a configurable number of
  attempts. Permanent failures (bad key, blocked content) fail at once. Bills
  stuck in processing are recovered automatically.
- **Matching:** the supplier is matched by fuzzy company name. Each line is
  matched by this supplier's SKU, then MPN, IPN, another supplier's SKU, and
  finally fuzzy part name. Every match carries a confidence score, and
  ambiguous codes are never trusted.
- **Review panel** (React, using InvenTree's own React and Mantine): edit
  header fields, quantities, prices and parts, skip lines, and see
  low-confidence and unmatched lines highlighted.
- **Receive:** one click creates the purchase order, places it and receives
  the stock into a chosen location, in a single database transaction. A
  supplier part is created when needed.
- **Duplicate protection** by file hash on upload, and by supplier and
  normalised bill number on receipt. This also checks existing purchase
  orders, and is backed by a database constraint.
- **Audit log** of uploads, edits, deletions and confirmations, with user,
  time and details.
- **REST API** under `/plugin/bill-scanner/api/`, using InvenTree's role
  permissions.
- **Settings:** API key (protected), model, API host, timeout, attempts, upload
  size, name match threshold, low-confidence threshold.
- **Accuracy evaluation** (`eval/`): runs bills through the plugin's own
  extraction and matching code and reports field, line, matching and
  confidence metrics against ground truth.
- **Developer tooling:** a private dev instance (`dev/`), demo data with a
  sample bill, backend tests (100% line coverage) and frontend tests.
- Documentation: README, code walkthrough, first-test checklist, demo guide,
  contributing guide, security policy, and GitHub issue and PR templates
  and CI.

### Security

- The Gemini API key is sent only in a request header, and only to
  `googleapis.com` hosts (checked on save and before every call). It is
  masked in stored and logged error messages.
- The background task receives only the bill ID, never the file.

[Unreleased]: https://github.com/nisha-karithikeyan/inventree-bill-scanner/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/nisha-karithikeyan/inventree-bill-scanner/releases/tag/v0.1.0
