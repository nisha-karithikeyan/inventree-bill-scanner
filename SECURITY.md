# Security policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| 0.1.x   | Yes       |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Email **[nishakarithikeyan@gmail.com](mailto:nishakarithikeyan@gmail.com)**
with:

- a description of the problem and its impact,
- steps to reproduce, or a proof of concept,
- the plugin and InvenTree versions you used.

Do not include real API keys or real supplier bills. Use fictional data.

You will get an acknowledgement as soon as possible, usually within a week.
Once the problem is confirmed, a fix is prepared and released, and you are
credited in the changelog unless you prefer not to be. Please give a
reasonable amount of time to fix the problem before disclosing it publicly.

This policy covers this plugin only. For InvenTree itself, follow
[InvenTree's security policy](https://docs.inventree.org/en/latest/security/).

## Security design

What the plugin does to protect the Gemini API key and uploaded bills. Every
point is covered by the backend test suite, except the one marked *(code
review only)*.

### Gemini API key

- **Stored as a protected plugin setting.** InvenTree's settings API returns
  it as `***`. The review panel only receives a true/false "a key is set" flag.
  Never put the key in code, environment files or commits.
- **Sent in a header, not the URL.** The key travels only in the
  `x-goog-api-key` request header, so it does not appear in URLs, proxy logs
  or browser history.
- **Host allowlist.** The key and the bill are sent only to the host in the
  *Gemini API Host* setting, and that host must be `googleapis.com` or a
  subdomain of it. Schemes, credentials, ports, query strings and fragments
  are refused. The check runs when the setting is saved and again before
  every call, so a value written to the database another way is still
  refused.
- **Masking.** If an error message from Gemini, or from the network layer,
  contains the key, it is replaced with `***` before it is stored on the bill
  or logged. The chained `requests` exception, whose request object holds the
  key header, is dropped.

### Uploaded bills

- **File type is checked from the bytes.** Only PDF, JPEG, PNG, WebP and
  HEIC/HEIF are accepted, detected from the file's magic bytes rather than the
  name or the browser's content type. Size is limited by the *Maximum Upload
  Size* setting.
- **The task queue never sees the file.** The background task receives only
  the bill's database ID, so the file is not stored in django-q's task table.
- **No bill bytes in local variables** *(code review only)*. The extraction
  task does not keep the file content in a named local variable, so error
  reporters that capture stack variables (such as Sentry, if enabled in
  InvenTree) cannot include it.
- **Files stay in InvenTree's media storage** under `bill_scanner/`, and are
  removed when a bill is deleted. They are sent to Google's Gemini API for
  extraction, and nowhere else.

### Access control

- Every endpoint uses InvenTree's role permissions: purchase order *view*,
  *add*, *change* or *delete*. Receiving a bill also needs stock *add*.
- Received bills cannot be edited or deleted. Confirming runs in one database
  transaction, with a row lock and a unique constraint against duplicate
  receipts.
- Every upload, edit, deletion and confirmation is written to an audit log
  with the user and time.

### Known limits

- Bills are processed by Google. Check that this is acceptable for your data
  before enabling the plugin.
- Like every InvenTree setting, the key is stored in plain text in the
  database. Anyone with database or backup access can read it.
- The plugin relies on InvenTree for authentication, sessions, CSRF
  protection and media access control.
