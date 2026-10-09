# First real end-to-end test

This guide walks through one real bill, from upload to stock received, using
the dev instance in `.dev/` and a real Gemini API key.

## 1. Start the dev instance

You need three terminals, all opened in the plugin folder:

| Terminal | Command          | What it runs                                    |
| -------- | ---------------- | ----------------------------------------------- |
| 1        | `dev/server.sh`  | Django on http://localhost:8000                 |
| 2        | `dev/worker.sh`  | django-q2 worker: Gemini calls and retries      |
| 3        | `dev/ui.sh`      | InvenTree's React UI on http://localhost:5173   |

Run `dev/setup.sh` once beforehand if you have not done so yet. Run
`dev/seed_demo.sh` as well if you want parts to match against.

Start the worker. Without it, InvenTree runs the task inside the upload
request: the browser then waits for Gemini, and failed bills are never retried.

## 2. Enter the Gemini API key

1. Open http://localhost:5173/web/settings/admin/plugin and log in as `admin`.
   The menu path is: your user name (top right) → **Admin Center** →
   **Plugins**.
2. In the plugin table, click the **Bill Scanner** row. A drawer opens.
3. Under **Plugin Settings**, click the edit button next to **Gemini API Key**.
4. Paste the key and press **Submit**. The value now shows as `***`.

If you can't see the Bill Scanner row, check **Plugin Settings** on the same
page: all four integrations (app, URL, interface, schedule) must be on.

### Where the key goes, and where it does not

- The key is stored in InvenTree's database as a *protected* plugin setting.
  The settings API returns it as `***` and the panel only learns whether a key
  exists. Anyone with database or backup access can read it, as with every
  InvenTree setting.
- The key is sent only in the `x-goog-api-key` header to the host in
  **Gemini API Host**. The plugin accepts only `googleapis.com` hosts, both
  when you save the setting and again before every call.
- If an error message ever contains the key, it is replaced with `***` before
  it is saved on the bill or logged.
- Never type the key into a terminal command, an `.env` file in this repo, a
  screenshot, or a chat message. Set it only in the UI as above.

### Where the bill goes

- The file is saved under `.dev/media/bill_scanner/` (in production: InvenTree's
  media folder). Logged-in InvenTree users can open it from the panel.
- The worker task receives only the bill's ID, so the file never reaches the
  task queue table or the worker logs.
- The file is sent once per attempt to Gemini, and nowhere else.
- The task keeps the file bytes out of named local variables, so error
  reporters that capture stack variables (such as Sentry, if you turn it on)
  never see the bill.
- `.dev/`, `eval/bills/` and `eval/results/` are gitignored. Keep real bills
  in those folders only.

## 3. Checklist

Work through these in order and tick each one off.

**Upload**

- [ ] Go to **Purchasing**, then **Scanned Bills** in the left sidebar
      (under *Plugin Provided*).
- [ ] The orange "Gemini API key missing" banner is gone.
- [ ] Click **Upload bill** and choose a photo or PDF (JPEG, PNG, WebP, HEIC
      or PDF, up to 15 MB).
- [ ] A new row appears with status **Waiting for extraction** or
      **Extracting**.

**Background task**

- [ ] Terminal 2 (worker) shows the task being processed. If it fails you
      see a `Bill <id> extraction failed: ...` warning.
- [ ] Optional: **Admin Center → Background Tasks** shows the task under
      *Pending Tasks* while it runs. The *Scheduled Tasks* list includes
      `bill_scanner.tasks.retry_due_bills`.
- [ ] Within about 10–60 seconds the status changes to **Ready for review**.
      The panel refreshes by itself every 3 seconds.
- [ ] If it shows **Waiting to retry** or **Extraction failed**, open the
      bill: the **Extraction problem** box (orange while retrying, red once
      failed) shows the reason and the attempt number. Copy it for diagnosis.

**Review**

- [ ] Click the row. Supplier, bill number, date and currency are filled in.
- [ ] Each line shows the description, quantity, unit price, a **Read**
      score (Gemini's confidence) and a **Match** badge.
- [ ] Yellow rows are low confidence; red rows have no part. Pick a part for
      each red row or tick **Skip**.
- [ ] Change one quantity or price and click elsewhere. The value stays after
      a page reload.
- [ ] Pick a **Receive into location** (optional).

**Confirm**

- [ ] Click **Create order and receive**. The status changes to
      **Purchase order created** and the fields lock.
- [ ] Click **View purchase order**.

**Check InvenTree**

- [ ] The purchase order has the right supplier, the bill number as
      *Supplier Reference*, one line per bill line with quantity and price, and
      status **Complete** (InvenTree completes an order automatically once
      every line is received).
- [ ] On each part's **Stock** tab, a new stock item exists with the received
      quantity in the chosen location.
- [ ] Upload the **same file** again: it is refused with "This file has
      already been uploaded".
- [ ] Optional: audit trail at
      http://localhost:8000/plugin/bill-scanner/api/bills/<id>/audit/ shows
      *uploaded*, any edits, and *confirmed* with your user name.

## 4. If something fails

Paste the following and I'll diagnose the root cause before changing code:

- the message shown on the bill or in the browser notification,
- the last 30 lines of the server and worker terminals,
- what you clicked just before it happened.

Check the output before pasting it: the plugin never logs the key or the
file, but your shell history or other tools might.
