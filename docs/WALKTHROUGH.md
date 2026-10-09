# How the bill scanner works

A guided tour of the code, in the order a bill travels through it. File and
function names are real, so you can open each one while you read.

**In one sentence:** a shop owner uploads a photo of a supplier bill, Gemini
reads it into structured JSON in a background task, each line is matched to a
part in InvenTree, a person checks and corrects it in a React panel, and one
click creates a purchase order and puts the stock on the shelf.

```text
 Browser (React panel)          Django web server                 django-q2 worker              Google
 ─────────────────────          ─────────────────                 ────────────────              ──────
 Upload bill ───────────────▶ BillList.post
                               validate, hash, save Bill
                               on_commit → offload_task ────────▶ extract_bill
                                                                  _claim (lock row)
 polls every 3 s ◀──────────── GET bills/                         request_extraction ──────────▶ Gemini
                                                                  parse_extraction ◀──────────── JSON
                                                                  save_extraction
                                                                  match_bill
 review, edit lines ────────▶ BillDetail / BillLineDetail
 Create order and receive ──▶ BillConfirm → confirm_bill
                               PurchaseOrder, place, receive,
                               StockItems, audit entry
```

---

## 1. The request flow, from upload to stock received

### 1.1 The plugin is registered

`pyproject.toml` declares an entry point in the `inventree_plugins` group:
`BillScanner = "bill_scanner.core:BillScannerPlugin"`. When InvenTree starts,
its plugin registry finds that entry point and loads the class.

`BillScannerPlugin` in `bill_scanner/core.py` is built from InvenTree's own
mixins. Each mixin adds one ability:

| Mixin                 | What it gives the plugin                                         |
| --------------------- | ---------------------------------------------------------------- |
| `AppMixin`            | Registers `bill_scanner` as a Django app, so it can have models and migrations |
| `SettingsMixin`       | The `SETTINGS` dict becomes the settings page (API key, model, thresholds) |
| `UrlsMixin`           | `setup_urls()` mounts the REST API under `/plugin/bill-scanner/` |
| `ScheduleMixin`       | `SCHEDULED_TASKS` registers `retry_due_bills` to run every minute |
| `APICallMixin`        | `api_call()` for outgoing HTTP, using the host and key settings  |
| `UserInterfaceMixin`  | `get_ui_panels()` adds the Scanned Bills panel to a page         |

### 1.2 Upload

1. The user picks a file in the panel. `BillClient.upload()` in
   `frontend/src/client.ts` posts it as multipart form data to
   `/plugin/bill-scanner/api/bills/`.
2. `BillList.post()` in `bill_scanner/api.py` handles it:
   - `BillUploadSerializer.validate_file()` (`serializers.py`) checks the size
     against `MAX_UPLOAD_MB`. It then reads the first 16 bytes and calls
     `sniff_content_type()` (`gemini.py`) to learn the real type from the
     file's magic bytes. The browser's claimed type is ignored, so a renamed
     `.exe` is refused.
   - `sha256_of()` (`models.py`) hashes the file in 64 KB chunks. If a bill
     with that hash exists, the answer is **409 Conflict**.
   - A `Bill` row is saved with status `pending`. The file goes to
     `media/bill_scanner/<hash[:2]>/<hash>/<name>`.
   - `BillAuditLog.record(..., UPLOADED)` writes the first audit entry.
   - `transaction.on_commit(lambda: queue_extraction(bill))` queues the
     background task **only after** the database commit. Otherwise the worker
     might look for a row that doesn't exist yet.
3. The view returns the new bill with **201 Created**, and the panel selects it.

### 1.3 Extraction in the background

`queue_extraction()` (`tasks.py`) calls InvenTree's `offload_task()` with only
the bill's ID. The worker runs `extract_bill(bill_id)`:

1. `_claim()` locks the row (`select_for_update`). It only proceeds if the bill
   is `pending` or `retry`, sets it to `processing`, and counts the attempt.
   Two workers can therefore never process the same bill.
2. `plugin.request_extraction()` (`core.py`) builds the Gemini request with
   `build_request()`, sends it through `api_call()`, and decodes the reply with
   `read_response()`.
3. `parse_extraction()` (`extraction.py`) validates and cleans the JSON into
   an `ExtractedBill` dataclass.
4. `save_extraction()` stores the header fields and the raw JSON, replaces the
   lines, and sets the status to `review`, all in one transaction.
5. `match_bill()` (`matching.py`) picks the supplier and a part for each line.

### 1.4 Review

The panel polls `GET bills/` every 3 seconds while any bill is busy. When the
status is `review`, `BillReview` shows the header and `LineTable` shows the
lines.

- Header edits go to `PATCH bills/<id>/` (`BillDetail.perform_update`). If the
  supplier changes, `match_bill(..., detect_supplier=False)` re-matches the
  lines, because supplier SKUs depend on the supplier.
- Line edits go to `PATCH bills/<id>/lines/<n>/` (`BillLineDetail`). If the
  user picks a part, the match becomes `manual` with confidence 1.0, and a
  later re-match leaves it alone.
- Every edit is written to the audit log with the changed fields.

### 1.5 Confirm

**Create order and receive** posts to `bills/<id>/confirm/`. `BillConfirm`
checks the `stock.add` role, validates the optional location, and calls
`confirm_bill()` in `services.py`. That function creates and places the
purchase order, receives every line, marks the bill `completed`, and writes
the audit entry (details in section 6).

---

## 2. The background task and retries

**Why a background task?** A Gemini call takes 5–60 seconds. Doing it inside
the upload request would block a web worker and risk HTTP timeouts. InvenTree
already runs django-q2 for background work, so the plugin uses its
`offload_task()` instead of adding Celery or threads.

**The states** (`Bill.Status` in `models.py`):

```text
pending → processing → review → completed
              │  ▲
              ▼  │ (after backoff)
             retry
              │
              ▼
            failed  ── "Read again" ──▶ pending
```

**Errors are sorted into two kinds** (`gemini.py`):

| Kind                    | Examples                                                    | What happens         |
| ----------------------- | ----------------------------------------------------------- | -------------------- |
| `TransientGeminiError`  | Timeout, connection error, HTTP 408/429/5xx, no candidates, malformed JSON | Retry later          |
| `PermanentGeminiError`  | No API key, HTTP 400/401/403/404, blocked content, safety stop | Fail at once         |

`ExtractionError` (the reply parsed but has no usable lines) counts as
retryable, because the model often reads a bill correctly on a second try. Any
other exception is a bug: it is logged with InvenTree's `log_error()` and the
bill fails without a retry.

**How a retry happens:** `_fail()` sets the status to `retry` and
`next_attempt_at = now + retry_delay(attempts)`. The delay is
`30 s × 2^(attempt − 1)`: 30 s, then 60 s, then 120 s. After `MAX_ATTEMPTS`
(default 3) the bill becomes `failed`.

The worker does not sleep while waiting. `retry_due_bills()` is a
`ScheduleMixin` task that runs every minute. It requeues bills whose
`next_attempt_at` has passed. It also rescues bills stuck in `processing` for
more than 15 minutes, for example when a worker was killed in the middle of a
call.

**Why not django-q's own retries?** `queue_extraction()` passes `retry=False`.
If both systems retried, a failure could be repeated without being counted,
and the attempt counter shown in the UI would be wrong. With one owner of the
retry logic, `attempts` is always the truth.

---

## 3. Prompts and structured output

Everything sent to Gemini is in `extraction.py` and `gemini.py`.

**The request** (`build_request()`) has two parts in one user message:

1. The file itself as `inline_data`: base64 bytes plus the sniffed MIME type.
   Gemini reads images and PDFs natively, so no OCR step is needed.
2. `PROMPT`: a short instruction. It says to read the supplier, bill number,
   date and each line; give unit prices before tax (and divide a line total by
   the quantity if only the total is printed); use `YYYY-MM-DD` dates and ISO
   currency codes; skip tax, shipping and discount rows; and lower the
   confidence for anything unclear.

**Structured output:** `generationConfig` sets
`responseMimeType: application/json` and `responseSchema: RESPONSE_SCHEMA`.
This makes Gemini return JSON in exactly that shape, with no prose and no
markdown fences. The schema lists `supplier_name`, `bill_number`, `bill_date`,
`currency` and `lines[]` with `description`, `sku`, `quantity`, `unit_price`
and `confidence`. `temperature: 0` makes the answer as repeatable as possible.

**Never trust the model blindly.** `parse_extraction()` cleans everything:

- `parse_decimal()` accepts `"1,234.50"`, `"1.234,50"`, `"$12"` and plain
  numbers. Whichever separator comes last is treated as the decimal point.
- `parse_date()` tries several common date formats and returns `None` rather
  than guessing.
- `clamp_confidence()` forces 0–1, and turns `95` into `0.95` (models
  sometimes answer in percent).
- Lines without a positive quantity are dropped. Negative prices become
  "no price". Text is trimmed to the column sizes.
- A currency must be three letters, otherwise it is left blank.

`read_response()` also checks `promptFeedback.blockReason` and each
candidate's `finishReason`, so a safety block becomes a clear permanent error
instead of a confusing parse failure.

---

## 4. Matching and confidence scores

All of this is in `matching.py`. There are two confidence numbers per line,
and they mean different things:

- **Read confidence** (`BillLine.confidence`): Gemini's own estimate of how
  clearly it read the line.
- **Match confidence** (`BillLine.match_confidence`): how sure the matcher is
  that the chosen part is right.

### Supplier

`match_supplier()` compares the bill's supplier name with every active
supplier company. Both names go through `normalize_company()`, which
lowercases them and strips suffixes such as Ltd, GmbH and Inc. They are then
compared with rapidfuzz `token_sort_ratio`. A score of at least 80 links the
company, and the score becomes `supplier_confidence`.

### Parts: codes first, names last

`PartMatcher.match()` tries the most reliable evidence first and stops at the
first hit:

| Order | Method          | How                                                        | Confidence |
| ----- | --------------- | ---------------------------------------------------------- | ---------- |
| 1     | `supplier_sku`  | Printed SKU equals one of **this supplier's** SupplierPart SKUs | 1.00   |
| 2     | `mpn`           | Equals a ManufacturerPart MPN                              | 0.92       |
| 3     | `ipn`           | Equals a Part IPN                                          | 0.92       |
| 4     | `sku`           | Equals another supplier's SKU                              | 0.85       |
| 5     | `name`          | Fuzzy match of the description against part names          | ≤ 0.90     |

Details that matter:

- **Codes are compared normalised** (`normalize_code()`): `"ACM-M3 10"` equals
  `"acm/m3-10"`.
- **Codes hidden in the description count too.** `code_candidates()` pulls
  out tokens with both letters and digits (such as `RC0603-10K`) and tries
  them at 95% of the normal confidence.
- **Ambiguity means no match.** For MPN, IPN and other-supplier SKU, the code
  must point to exactly one part. If two parts share it, the matcher moves on
  rather than guessing.
- **Name matching** uses rapidfuzz `token_set_ratio` over "name +
  description" of active, purchaseable parts, with a minimum score of `MATCH_MIN_SCORE`
  (default 70). Confidence is `score/100 × 0.9`, so a name match is never as
  trusted as a code. Parts this supplier already supplies get +0.05, which
  breaks ties sensibly. The result is capped at 0.90.
- **Why `token_set_ratio` and not `WRatio`?** The demo bill caught a real
  bug. `WRatio` includes a partial token-set step that scores about 85 as
  soon as two strings share *any* token. "USB C to C cable 1 m" shared only
  the unit letter `m` with "Jumper wires M-M", tied with the real cable at
  85.5, and the same-supplier bonus then picked the jumper wires.
  `token_set_ratio` scores them 87.5 and 40.8. A regression test
  (`test_shared_unit_letter_is_not_a_match`) keeps it fixed.
- **Lookups are cached per bill.** The supplier's SKUs and the part names are
  `cached_property` values on the matcher, so a 30-line bill does not run 30
  identical queries.

### What the panel highlights

`frontend/src/confidence.ts` colours each row by the **weaker** of the two
confidences. Below `LOW_CONFIDENCE` (default 0.75) the row is yellow. With no
part at all it is red, and the order cannot be created until the user picks a
part or ticks Skip.

---

## 5. How duplicate bills are blocked

There are three layers, from cheapest to strongest:

1. **Same file:** `Bill.file_hash` is `unique=True`. The upload view checks the
   SHA-256 first and answers **409** with a link to the existing bill. The
   unique index also stops two uploads racing each other.
2. **Same supplier and bill number:** `find_duplicate()` in `services.py` runs
   at confirm time. It normalises the bill number (`normalize_bill_number()`:
   `"INV-001 "` and `"inv 001"` both become `INV001`) and looks for:
   - another `completed` bill for this supplier with the same `bill_key`, or
   - any existing purchase order for this supplier whose
     `supplier_reference` normalises to the same value. This also catches a
     bill that was entered by hand without the scanner.

   If either exists, the answer is **409** with the conflicting bill or order.
3. **Database constraint:** `bill_scanner_unique_received_bill` is a
   `UniqueConstraint` on `(supplier, bill_key)` that applies only when
   `status='completed'`. If two people confirm the same bill number at the
   same moment, both may pass the check, but only one can commit.

`bill_key` is set only when a bill is received. This is deliberate: two
uploads of the same bill may both sit in review, and only receiving the second
one is blocked.

---

## 6. Creating the purchase order and stock, and the audit log

`confirm_bill()` in `services.py` is wrapped in `@transaction.atomic`. If any
step fails, nothing is kept: no half-created order and no orphan stock.

1. **Lock and check.** The bill row is locked with
   `select_for_update(of=('self',))`. It must be in `review` and have a
   supplier, a bill number and at least one non-skipped line, and every line
   must have a part. Then `find_duplicate()` runs.
2. **Currency:** the bill's own currency, else the supplier's default, else
   InvenTree's default currency.
3. **Purchase order:** a `PurchaseOrder` with the supplier, the bill number as
   `supplier_reference`, the user as `created_by`, and the chosen location as
   `destination`. If InvenTree requires a responsible owner
   (`PURCHASEORDER_REQUIRE_RESPONSIBLE`), the user's `Owner` is set.
4. **Line items:** for each line, `_supplier_part_for()` uses the matched
   supplier part if it belongs to this supplier. Otherwise it reuses one with
   the same SKU, or creates a new `SupplierPart` (SKU from the bill, or
   `BILL-<IPN>`). A purchase order line needs a supplier part, not just a part.
   Each `PurchaseOrderLineItem` gets the quantity, the price as a `Money`
   value, and a reference "Bill line N".
5. **Place and receive** with InvenTree's own methods: `order.place_order()`,
   then `order.receive_line_items(location, lines, user)`. Calling the core
   methods instead of creating stock rows directly means InvenTree's
   validation, stock tracking history, pricing updates and auto-completion of
   the order all happen exactly as for a manual receipt.
6. **Finish the bill:** status `completed`, link to the order, and the
   normalised `bill_key`.
7. **Audit entry:** `BillAuditLog.record(..., CONFIRMED)` stores the order,
   the stock item IDs, the location, the currency, and every line with its
   part, supplier part, quantity, price and match method, plus the skipped
   lines.

**The audit log** (`BillAuditLog`) records uploads, header edits, line edits,
deletions and confirmations, each with the user and a timestamp. The `bill`
foreign key is `SET_NULL`, and `bill_label` keeps a readable name, so entries
outlive a deleted bill. Received bills cannot be deleted or edited at all
(`ensure_editable()` and `perform_destroy()`).

**Permissions** reuse InvenTree's roles through `RolePermission`: viewing
needs `purchase_order.view`, uploading needs `add`, editing needs `change`,
and deleting needs `delete`. Confirming needs `purchase_order.add` and also
`stock.add`, because it creates stock.

---

## 7. How the React panel plugs into InvenTree

**Server side.** `get_ui_panels()` in `core.py` returns a panel description
only when `context['target_model'] == 'purchasing'`, which is the Purchasing
index page, and only for users with `purchase_order.view`. The description
contains:

- `source: plugin_static_file('BillScanner.js:renderBillScannerPanel')`:
  the URL of the compiled file plus the name of the function to call, and
- `context: ui_context(user)`: the API base path, the thresholds, whether a key
  is set (never the key itself), and the user's edit and confirm rights.

**Client side.** InvenTree's `RemoteComponent` imports that JavaScript module,
calls `renderBillScannerPanel(context)`, and renders the returned React element
inside its own component tree. The context it passes includes InvenTree's
`api` object (an axios instance that already carries the session and CSRF
token), so the panel never handles authentication itself.

**Build.** `frontend/vite.config.ts` builds a single ES module into
`bill_scanner/static/BillScanner.js`. React, ReactDOM, Mantine core and
Mantine notifications are marked as *externals* and read from the globals
InvenTree exposes (`window.React`, `window.MantineCore`, ...). That keeps the
bundle around 18 KB and, more importantly, means there is only **one** React
instance. Two copies of React would break hooks and theming. When InvenTree
runs `collectplugins`, the file is copied to `/static/plugins/bill-scanner/`.

**Components** (`frontend/src/`):

| File                         | Job                                                       |
| ---------------------------- | --------------------------------------------------------- |
| `BillScanner.tsx`            | Panel root: list state, upload, polling, notifications    |
| `client.ts`                  | Typed `BillClient` for the plugin API and part, supplier and location search |
| `components/BillList.tsx`    | Upload button, API-key warning, table of bills            |
| `components/BillReview.tsx`  | Header form, actions (read again, delete, confirm)        |
| `components/LineTable.tsx`   | Editable lines, confidence badges, row colours            |
| `components/RemoteSelect.tsx`| Searchable select backed by InvenTree's REST API          |
| `confidence.ts`              | Row colour rules and "why can't I confirm yet" message    |

---

## 8. Design decisions, trade-offs, and what I would improve

### Decisions and why

| Decision | Why | Cost |
| -------- | --- | ---- |
| A plugin, not a fork of InvenTree | Upgrades stay painless and the repo stays untouched | Limited to what the mixins expose (see the `lazy_view` workaround below) |
| Gemini reads the image directly, no OCR | One call handles layout, tables, handwriting and PDFs | Data leaves the server; cost per call; non-deterministic |
| Structured output with a JSON schema | No fragile parsing of free text | The model can still put wrong values in the right shape, hence `parse_extraction()` |
| Human review before anything is created | AI mistakes never reach stock or accounts silently | One extra step for the user |
| Own retry bookkeeping, django-q retries off | One source of truth for attempts and backoff | A little more code (`_claim`, `_fail`, `retry_due_bills`) |
| Codes before fuzzy names, ambiguity = no match | A wrong match is worse than no match | More lines need a manual pick |
| Use `place_order()` and `receive_line_items()` | InvenTree's rules, history and pricing stay correct | Tied to those method signatures |
| One transaction for confirm | No half-received orders | A long transaction for very large bills |
| Externals for React and Mantine | Small bundle, shared theme, one React | Must match InvenTree's major versions |

**`lazy_view` in `core.py`.** InvenTree builds the plugin URLs before
`AppMixin` has registered the app, so the views (which import the models)
cannot be imported at that moment. `lazy_view()` imports the real DRF view on
the first request instead. It is a small workaround, and it is documented in
the code.

**Privacy.** The key is a protected setting, it is sent only in a header, and
only to `*.googleapis.com` hosts (checked when the setting is saved and before
every call). It is redacted from stored errors. The worker receives only the
bill's ID. The file itself does go to Google, which the README states plainly.

### What I would improve next

1. **Arithmetic cross-checks.** Ask Gemini for line totals and the bill total,
   then check `quantity × unit_price ≈ line total` and that the lines add up to
   the total. A mismatch would lower the confidence. This catches the most
   common error, a misread digit, which the model's self-reported confidence
   often misses (the eval measures exactly this).
2. **Learn from corrections.** When a user picks a part manually, offer to
   save the printed SKU as a SupplierPart. The next bill from that supplier
   then matches at 100%.
3. **Scale the name matching.** `part_names` loads every purchaseable part
   into memory. That is fine for thousands of parts; for 100k or more I would
   use PostgreSQL trigram search, or embeddings, to shortlist candidates.
4. **Faster duplicate lookup.** `find_duplicate()` loops over the supplier's
   purchase orders in Python to normalise `supplier_reference`. A stored,
   indexed normalised reference would make it a single query.
5. **Units and pack sizes.** Bills often say "2 boxes of 100". Map that to the
   SupplierPart `pack_quantity` instead of trusting the raw quantity.
6. **Large files.** Inline data is limited to about 20 MB. The Gemini Files
   API would allow bigger multi-page PDFs.
7. **Push instead of polling.** Replace the 3-second polling with
   server-sent events, or InvenTree notifications, when a bill is ready.
8. **Data residency.** Support Vertex AI regional endpoints with service
   accounts, for customers who cannot send data to the global API.

---

## 9. Likely interview questions

Fifteen likely questions, plus one more about a real bug.

**1. Walk me through what happens when a user uploads a bill.**
The view validates the size and the real file type from its magic bytes,
hashes it, and refuses duplicates with a 409. It saves a `Bill` in `pending`,
writes an audit entry, and after the commit queues `extract_bill` on
django-q2 with just the bill ID. The worker locks the row, calls Gemini with
the file and a JSON schema, cleans the reply, saves the lines and runs the
matcher. The bill is then in `review` for a human.

**2. Why a background task instead of calling Gemini in the request?**
Calls take up to a minute. Blocking a web worker that long hurts everyone
else and risks gateway timeouts. InvenTree already ships django-q2, so I used
its `offload_task()` and `ScheduleMixin` rather than adding infrastructure.

**3. How do retries work, and why did you turn off django-q's retries?**
Errors are classified as transient (timeouts, 429, 5xx, malformed JSON) or
permanent (bad key, blocked content). Transient errors set `retry` with
exponential backoff (30 s, 60 s, 120 s), and a scheduled task requeues due
bills every minute. Django-q retries are off so there is one owner of the
attempt count; otherwise redeliveries would not be counted.

**4. What if a worker dies mid-call?**
The bill stays in `processing`. `retry_due_bills()` treats anything in
`processing` for more than 15 minutes as stuck and moves it to `retry`, so it
is picked up again.

**5. How do you stop two workers processing the same bill?**
`_claim()` uses `select_for_update()` inside a transaction and only moves a
bill from `pending` or `retry` to `processing`. The second worker sees
`processing` and returns.

**6. How do you get reliable JSON out of an LLM?**
Gemini's structured output: `responseMimeType: application/json` plus a
`responseSchema`, with temperature 0. I still validate everything in
`parse_extraction()`: numbers with either decimal separator, several date
formats, confidence clamped to 0–1, and dropping lines without a quantity.
The shape is guaranteed; the values are not.

**7. How does matching work?**
Most reliable evidence first: this supplier's SKU (1.0), then MPN or IPN
(0.92), then another supplier's SKU (0.85), then a fuzzy name match with
rapidfuzz, capped at 0.9. Codes are normalised, and codes embedded in the
description are tried too. If a code points to more than one part, I treat it
as no match rather than guess.

**8. What do the confidence numbers mean, and do you trust Gemini's?**
There are two: Gemini's read confidence and my match confidence. The panel
uses the weaker one to highlight rows. I don't fully trust self-reported
confidence, so the eval script measures it: average confidence on correct
versus wrong lines, and what share of wrong lines were actually highlighted.

**9. How are duplicate bills prevented?**
Three layers: a unique file hash checked on upload; at confirm time, a check
against received bills and existing purchase orders with the same supplier
and normalised bill number; and a conditional unique constraint on
`(supplier, bill_key)` for completed bills, which catches two simultaneous
confirms.

**10. Why not create stock items directly?**
`place_order()` and `receive_line_items()` are InvenTree's own code path.
They apply validation, write stock tracking history, update pricing and
auto-complete the order. Re-implementing them would drift from core behaviour.

**11. What happens if receiving fails halfway?**
`confirm_bill()` is one atomic transaction, so the order, its lines, the stock
items and the bill's status change all roll back together. A test patches
`receive_line_items` to fail and checks that nothing is left.

**12. How is the API key protected?**
It is a protected plugin setting, so the API returns `***`, and the panel only
gets a "has key" flag. It is sent in the `x-goog-api-key` header, never in the
URL, and only to `googleapis.com` hosts, which is checked on save and before
every call. It is redacted from any error text before that text is stored or
logged, and the chained requests exception is dropped.

**13. How does the React panel get into InvenTree without changing InvenTree?**
`UserInterfaceMixin.get_ui_panels()` returns a panel for the Purchasing page
with a `source` pointing to the compiled JS file and function. InvenTree
imports the module and renders the returned element in its own tree. I mark
React and Mantine as externals so the plugin uses InvenTree's copies: one
React, a shared theme, and an 18 KB bundle.

**14. How did you test it?**
The backend tests run inside InvenTree's own test runner with 100% line
coverage. They mock HTTP for Gemini, and cover parsing edge cases, retries,
matching ambiguity, permissions, duplicates, rollback and the audit log.
Frontend tests use vitest and Testing Library. Separately, an eval script runs
real bills through the exact same `extract_bill` code path, inside a
rolled-back transaction, and scores it against hand-written ground truth.

**15. Tell me about a bug you found.**
The demo bill matched "USB C to C cable 1 m" to jumper wires. I measured the
scores instead of tweaking thresholds: rapidfuzz's `WRatio` gave both parts
85.5, because its partial token-set step treats one shared letter (`m`) as a
near-perfect overlap, and my same-supplier bonus broke the tie the wrong way.
I wrote a failing regression test first, then switched the scorer to
`token_set_ratio` (87.5 vs 40.8). The lesson: a fuzzy score is only as good
as the scorer's worst case, so test it with realistic short descriptions.

**16. What would you do differently or next?**
Cross-check `quantity × price` against line and bill totals to catch
misread digits, save manual picks as supplier SKUs so matching improves over
time, move name matching to database trigram search for large catalogues,
and support pack sizes. I'd also replace polling with push notifications.
