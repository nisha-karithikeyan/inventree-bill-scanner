# inventree-bill-scanner

**Turn a photo or PDF of a supplier bill into a received purchase order in
[InvenTree](https://inventree.org), with Google Gemini doing the reading and a
human checking the result.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![InvenTree: tested with 1.6 dev](https://img.shields.io/badge/InvenTree-tested%20with%201.6%20dev-informational.svg)](#requirements)
[![CI](https://github.com/nisha-karithikeyan/inventree-bill-scanner/actions/workflows/ci.yml/badge.svg)](https://github.com/nisha-karithikeyan/inventree-bill-scanner/actions/workflows/ci.yml)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

> **Status: beta (v0.1.0).** Extraction, matching and order creation are
> covered by automated tests, but the extraction has only been tested with
> mocked Gemini responses so far. Real-world accuracy results will be
> published in [`eval/results/`](eval/README.md) once they have been measured.

## What it does

```text
 bill photo / PDF  ──▶  Gemini reads it  ──▶  lines matched to your parts  ──▶  you review  ──▶  purchase order + stock received
```

1. **Upload** a bill on the **Purchasing → Scanned Bills** panel.
2. A background worker sends it to **Google Gemini**, which returns the
   supplier, bill number, date, currency and every line (description, SKU,
   quantity, unit price, confidence) as structured JSON.
3. Each line is **matched** to an existing part by supplier SKU, MPN, IPN or a
   fuzzy name match, and each match gets a confidence score.
4. You **review** the lines. Low-confidence and unmatched lines are
   highlighted. You can change any value, pick a different part or skip a line.
5. **Create order and receive** creates the purchase order, places it and
   receives the stock in one transaction. A bill that was already received is
   refused, and every action is written to an audit log.

<!-- Demo GIF: record it with docs/DEMO.md, save it as docs/demo/demo.gif, then
     replace this comment with:
![Demo: from bill photo to received purchase order](docs/demo/demo.gif)
-->

![Reviewing an extracted bill](docs/screenshots/bill-review.png)

<sub>Screenshot from the development instance with fictional demo data
(`dev/seed_demo.sh`, which uses a canned extraction reply).</sub>

## Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Settings](#settings)
- [Permissions](#permissions)
- [How it works](#how-it-works)
- [REST API](#rest-api)
- [Privacy and security](#privacy-and-security)
- [Development](#development)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [Acknowledgements](#acknowledgements)
- [Disclaimer](#disclaimer)
- [Author](#author)
- [License](#license)

## Requirements

- **InvenTree:** tested with InvenTree 1.6.0 (development version, commit
  [`800cbe0`](https://github.com/inventree/InvenTree/commit/800cbe0d30687124aaeb143dbca6e04c64c7cffd)),
  which is also what CI tests against. The plugin declares a minimum of 1.0.0,
  but versions before 1.6 have not been tested.
- **Python 3.12**, the only version tested.
- A running InvenTree **background worker** (`invoke worker` or
  `manage.py qcluster`).
- A **Google Gemini API key** from [Google AI Studio](https://aistudio.google.com/apikey).

## Installation

1. Install the package into the Python environment InvenTree runs in:

   ```bash
   pip install git+https://github.com/nisha-karithikeyan/inventree-bill-scanner
   # or, from a local checkout:
   pip install /path/to/inventree-bill-scanner
   ```

   For Docker installs, add the same `git+https://...` line to your
   `plugins.txt` file instead.

2. In **Admin Center → Plugin Settings**, turn on these integrations. The
   plugin needs all four:

   | Setting                      | Used for                     |
   | ---------------------------- | ---------------------------- |
   | Enable app integration       | The plugin's database tables |
   | Enable URL integration       | The plugin's REST API        |
   | Enable interface integration | The Scanned Bills panel      |
   | Enable schedule integration  | Retrying failed extractions  |

3. Restart InvenTree, then apply the migrations and collect the static files:

   ```bash
   invoke migrate          # or: manage.py migrate
   invoke static           # or: manage.py collectplugins
   ```

4. In **Admin Center → Plugins**, activate **Bill Scanner** and open its
   settings. Paste your key into **Gemini API Key**.

5. Make sure the background worker is running. Without it, uploaded bills stay
   in "Waiting for extraction".

[docs/FIRST_TEST.md](docs/FIRST_TEST.md) walks through a first end-to-end test.

## Settings

| Setting                  | Default                                    | Meaning                                                                  |
| ------------------------ | ------------------------------------------ | ------------------------------------------------------------------------ |
| Gemini API Key           | (empty)                                    | Required. Stored as a protected setting and never sent to the browser.   |
| Gemini Model             | `gemini-2.5-flash`                         | A Gemini model that accepts images and PDFs.                              |
| Gemini API Host          | `generativelanguage.googleapis.com/v1beta` | Only `googleapis.com` hosts are accepted (regional endpoints are fine).  |
| Request Timeout          | 120 s                                      | How long one Gemini call may take.                                       |
| Maximum Attempts         | 3                                          | Total tries for a bill before it is marked failed.                       |
| Maximum Upload Size      | 15 MB                                      | Largest accepted file (Gemini's inline data limit is about 20 MB).       |
| Minimum Name Match Score | 70                                         | Fuzzy name matches below this score (0–100) are ignored.                  |
| Low Confidence Threshold | 75                                         | Lines below this confidence (0–100) are highlighted.                     |

## Permissions

The plugin uses InvenTree's existing roles. No new roles are added.

| Action                   | Needs                                  |
| ------------------------ | -------------------------------------- |
| See the panel and bills  | Purchase order: view                   |
| Upload a bill            | Purchase order: add                    |
| Edit lines, read again   | Purchase order: change                 |
| Delete a bill            | Purchase order: delete                 |
| Create order and receive | Purchase order: add **and** Stock: add |

## How it works

```mermaid
flowchart LR
    U([User]) -->|upload photo / PDF| API

    subgraph InvenTree web server
        API[REST API<br/>/plugin/bill-scanner/api/]
        Panel[Scanned Bills panel<br/>React, Purchasing page]
        Confirm[confirm_bill<br/>one DB transaction]
    end

    subgraph django-q2 worker
        Extract[extract_bill task]
        Retry[retry_due_bills<br/>every minute]
        Match[Part matcher<br/>SKU → MPN → IPN → fuzzy name]
    end

    DB[(Bill, BillLine,<br/>BillAuditLog)]
    Gemini[[Google Gemini<br/>generateContent]]

    API -->|store file + hash| DB
    API -->|offload_task| Extract
    Extract -->|image/PDF + JSON schema| Gemini
    Gemini -->|structured JSON| Extract
    Extract -->|parsed lines| DB
    Extract --> Match --> DB
    Retry -->|requeue after backoff| Extract
    Panel <-->|review, edit| API
    Panel -->|confirm| Confirm
    Confirm -->|PurchaseOrder, StockItems,<br/>audit entry| DB
```

### Bill lifecycle

```mermaid
stateDiagram-v2
    [*] --> pending: upload
    pending --> processing: worker picks it up
    processing --> review: extracted and matched
    processing --> retry: timeout, rate limit, bad JSON
    retry --> processing: after backoff (30 s, 60 s, 120 s, ...)
    processing --> failed: bad key, blocked file, attempts used up
    failed --> pending: Read again
    review --> pending: Read again
    review --> completed: Create order and receive
    completed --> [*]
```

### Code layout

| Module                       | Responsibility                                                           |
| ---------------------------- | ------------------------------------------------------------------------ |
| `bill_scanner/core.py`       | Plugin class: settings, URLs, UI panel, scheduled task, Gemini HTTP call |
| `bill_scanner/models.py`     | `Bill`, `BillLine`, `BillAuditLog`                                       |
| `bill_scanner/gemini.py`     | Request body, file type sniffing, host allowlist, error classification  |
| `bill_scanner/extraction.py` | JSON schema and prompt for Gemini; parsing and validating its reply     |
| `bill_scanner/tasks.py`      | Background extraction, retries with backoff, recovery of stuck bills    |
| `bill_scanner/matching.py`   | Supplier and part matching with confidence scores                       |
| `bill_scanner/services.py`   | Duplicate checks; creating, placing and receiving the purchase order    |
| `bill_scanner/api.py`        | REST views                                                               |
| `frontend/src/`              | React review panel, built into `bill_scanner/static/BillScanner.js`      |
| `eval/`                      | Accuracy evaluation against hand-written ground truth                   |

The plugin uses only InvenTree's public plugin mixins (`AppMixin`,
`APICallMixin`, `ScheduleMixin`, `SettingsMixin`, `UrlsMixin`,
`UserInterfaceMixin`) and its own models. It does not change any InvenTree
table. [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md) explains every step in
detail.

### Matching and confidence

Lines are matched in this order. The first hit wins.

| Method                         | Confidence | Notes                                                |
| ------------------------------ | ---------- | ---------------------------------------------------- |
| SKU of this supplier's part    | 100%       |                                                      |
| Manufacturer part number (MPN) | 92%        | Only when exactly one part has that MPN              |
| Internal part number (IPN)     | 92%        | Only when exactly one part has that IPN              |
| SKU of another supplier's part | 85%        | Only when exactly one part has that SKU              |
| Fuzzy name match               | up to 90%  | `rapidfuzz` token set ratio on name and description  |
| Chosen by user                 | 100%       | Set when you pick a part in the review table         |

Codes printed inside the description (for example "Resistor RC0603-10K") are
also tried, at 95% of the confidence above. Parts this supplier already
supplies get a small bonus when names tie. The supplier itself is matched by
fuzzy name, ignoring suffixes such as Ltd, GmbH or Inc.

The **Read** column in the review table is Gemini's own confidence in the
values it read. The **Match** column is the matcher's confidence in the part.
A line is highlighted when either is below the threshold or it has no part.

### Duplicate protection

A bill is refused when:

- the same file (by SHA-256) was uploaded before (HTTP 409 on upload), or
- a received bill, or any purchase order, from the same supplier already has
  the same bill number (HTTP 409 on confirm). Numbers are compared without
  case, spaces or punctuation, so `INV-001` and `inv 001` are the same bill.

A database constraint backs up the second check, so two people confirming at
the same moment cannot both succeed.

### Audit log

Every upload, header edit, line edit, deletion and confirmation is stored in
`BillAuditLog` with the user and a timestamp. A confirmation entry records the
purchase order, stock items, location, currency and every line with its part,
quantity, price and match method. Entries are kept even when a bill is
deleted. They are available at `GET /plugin/bill-scanner/api/bills/<id>/audit/`.

## REST API

All endpoints are below `/plugin/bill-scanner/api/` and use InvenTree's normal
authentication (session or token).

| Method | Path                       | Purpose                                                            |
| ------ | -------------------------- | ------------------------------------------------------------------ |
| GET    | `bills/`                   | List bills; filter with `?status=review,failed`                    |
| POST   | `bills/`                   | Upload a bill (multipart field `file`)                             |
| GET    | `bills/<id>/`              | Bill with header and lines                                         |
| PATCH  | `bills/<id>/`              | Correct supplier, bill number, date or currency                    |
| DELETE | `bills/<id>/`              | Delete a bill that has not been received                           |
| PATCH  | `bills/<id>/lines/<line>/` | Correct a line: part, supplier part, quantity, price, skip         |
| POST   | `bills/<id>/extract/`      | Read a failed or reviewed bill again                               |
| POST   | `bills/<id>/confirm/`      | Create the order and receive it; body `{"location": <id or null>}` |
| GET    | `bills/<id>/audit/`        | Audit trail of the bill                                            |

## Privacy and security

Uploaded bills are sent to Google's Gemini API. Check that this is allowed
for your data before you enable the plugin. Files are kept in InvenTree's
media folder under `bill_scanner/` until the bill is deleted.

- The API key is a protected setting: the API returns it as `***`, and the
  browser only learns whether a key is set.
- The key is sent only in the `x-goog-api-key` header, and only to
  `googleapis.com` hosts. This is checked when the setting is saved and again
  before every call.
- The key is masked in any error text before that text is stored or logged.
- The background task receives only the bill's ID, never the file.

See [SECURITY.md](SECURITY.md) for the full security design, and for how to
report a vulnerability privately.

## Development

The `dev/` scripts run a private InvenTree instance from a sibling InvenTree
checkout. All data (SQLite database, media, config) lives in `.dev/` in this
repository; nothing is written to the InvenTree source tree.
[CONTRIBUTING.md](CONTRIBUTING.md) has the full setup.

```text
parent/
├── InvenTree/                 # InvenTree source checkout (unchanged)
└── inventree-bill-scanner/    # this repository
```

```bash
# One-time: virtualenv with InvenTree's requirements and this plugin
python3.12 -m venv .venv
.venv/bin/pip install -r ../InvenTree/src/backend/requirements.txt \
                      -r ../InvenTree/src/backend/requirements-dev.txt
.venv/bin/pip install -e ".[dev]"

dev/setup.sh        # migrate, enable the plugin, create admin/admin
dev/demo.sh         # optional: demo supplier, 12 parts with stock, sample bill
dev/server.sh       # Django on http://localhost:8000
dev/worker.sh       # second terminal: background worker
dev/ui.sh           # third terminal: InvenTree's React UI on http://localhost:5173
```

Set `INVENTREE_SRC` if your InvenTree checkout is somewhere else.
`dev/demo.sh --fresh` first moves the dev database and media to
`.dev/backup/<time>/`, then starts from an empty instance. `dev/seed_demo.sh`
instead creates already-extracted demo bills from canned replies, for
screenshots without an API key.

### Tests

```bash
dev/test.sh                                   # backend, inside InvenTree's test runner
COVERAGE=1 dev/test.sh                        # with a coverage report
dev/test.sh bill_scanner.tests.test_matching  # one module
.venv/bin/python -m unittest discover eval    # eval scorer

cd frontend && yarn install
yarn typecheck
yarn test                                     # vitest + Testing Library
```

The backend suite never calls Gemini; HTTP responses are mocked. CI runs lint,
the backend tests and the frontend checks on every push and pull request, and
never needs an API key.

| Test module          | Covers                                                           |
| -------------------- | ---------------------------------------------------------------- |
| `test_plugin.py`     | Registration, settings, protected API key                        |
| `test_gemini.py`     | Request body, file sniffing, responses, allowed hosts, redaction |
| `test_extraction.py` | Parsing numbers, dates, confidence and malformed replies         |
| `test_tasks.py`      | Background task, retries, backoff, stuck bills, key never leaked |
| `test_upload_api.py` | Upload validation, file hash duplicates, deletion, permissions   |
| `test_matching.py`   | Supplier and part matching, confidence, ambiguity                |
| `test_review.py`     | Editing headers and lines, re-matching, UI panel                 |
| `test_confirm.py`    | Order creation, stock receipt, rollback, duplicates, audit log   |
| `test_edge_cases.py` | Disabled plugin, header validation, InvenTree errors             |
| `test_demo.py`       | Demo data is idempotent and the sample bill matches every line   |

### Building the panel

```bash
cd frontend
yarn build    # type-checks, then writes bill_scanner/static/BillScanner.js
```

The bundle uses InvenTree's own React and Mantine (exposed as `window.React`,
`window.MantineCore`, ...), so it stays small and shares InvenTree's theme.
The built file is committed so that `pip install` works without Node.

### Screenshots

`node dev/screenshots.mjs` recaptures the images in `docs/screenshots/` from a
running dev instance seeded with `dev/seed_demo.sh`.

| Bill list                                    | Received bill                                        |
| -------------------------------------------- | ---------------------------------------------------- |
| ![Bill list](docs/screenshots/bill-list.png) | ![Received bill](docs/screenshots/bill-received.png) |

## Documentation

| Guide                                      | For                                                       |
| ------------------------------------------ | --------------------------------------------------------- |
| [docs/FIRST_TEST.md](docs/FIRST_TEST.md)   | Entering the key and a first end-to-end test checklist    |
| [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md) | How the code works, design trade-offs, likely questions   |
| [docs/DEMO.md](docs/DEMO.md)               | A 30-second demo script and which screenshots to take     |
| [eval/README.md](eval/README.md)           | Measuring extraction and matching accuracy on your bills  |
| [CHANGELOG.md](CHANGELOG.md)               | What changed in each release                              |

## Contributing

Contributions, bug reports and ideas are all welcome, whether it's a typo, a
supplier bill layout that trips up the extraction, or a new feature. Please
read [CONTRIBUTING.md](CONTRIBUTING.md) to get started, and open an
[issue](https://github.com/nisha-karithikeyan/inventree-bill-scanner/issues)
if you want to discuss something first. Everyone taking part is expected to
follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Acknowledgements

Built on [InvenTree](https://inventree.org)
([GitHub](https://github.com/inventree/InvenTree)), the open-source inventory
management system, and its plugin framework. Thanks to the InvenTree
maintainers and community. Fuzzy matching uses
[RapidFuzz](https://github.com/rapidfuzz/RapidFuzz), and bills are read by
[Google Gemini](https://ai.google.dev/).

## Disclaimer

This is an independent community plugin. It is not affiliated with, endorsed
by or supported by the InvenTree project. Please report problems with this
plugin here, not to the InvenTree project.

## Author

**Nisha Karthikeyan**

- GitHub: [@nisha-karithikeyan](https://github.com/nisha-karithikeyan)
- Website: [nishakarithikeyan.framer.website](https://nishakarithikeyan.framer.website)

## License

[MIT](LICENSE) © 2026 Nisha Karthikeyan
