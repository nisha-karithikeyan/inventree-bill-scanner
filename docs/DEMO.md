# Demo recording

A 30-second screen recording: bill photo in, purchase order and stock out.

## Before you record

1. **Clean data.** Run `dev/demo.sh --fresh`. It moves the current dev
   database and media to `.dev/backup/<time>/`, creates a new instance with
   `admin`/`admin`, and seeds:
   - supplier **Brightline Components**
   - 12 parts with stock on **Main store / Shelf A**
   - the sample bill `docs/demo/sample-bill.png` (invoice BRL-INV-24817,
     8 lines)
2. **Key.** Enter your Gemini API key (see [FIRST_TEST.md](FIRST_TEST.md#2-enter-the-gemini-api-key)).
3. **Start** `dev/server.sh`, `dev/worker.sh` and `dev/ui.sh` in three
   terminals.
4. **Do one dry run** and confirm it, so you know the timing and that every
   line matches. Then run `dev/demo.sh --fresh` again and re-enter the key, so
   the recording starts clean. (A second confirm of the same bill would be
   refused as a duplicate.)
5. **The photo.** Print `docs/demo/sample-bill.png`, lay it on a desk and
   take a phone photo at a slight angle. A real photo is far more convincing
   than a clean PNG. Copy it to the recording machine as
   `brightline-invoice.jpg`.
6. **The screen.** Browser window about 1440×900 at 100% zoom, a light theme,
   no bookmarks bar. Close the red *Superuser Mode* banner with its ×.
7. **Two tabs, ready:**
   - Tab 1: **Parts → Resistor 10k 0603 → Stock** (shows 1200 on hand).
   - Tab 2: **Purchasing → Scanned Bills**.

## The 30 seconds

| Time      | On screen                                                                 | Say (optional voice-over)                         |
| --------- | ------------------------------------------------------------------------- | ------------------------------------------------- |
| 0:00–0:03 | Tab 1: Resistor 10k 0603 with **1200** in stock                           | "We have 1200 of these resistors."                |
| 0:03–0:07 | Tab 2: click **Upload bill**, choose `brightline-invoice.jpg`             | "A supplier bill arrives. I upload a photo of it."|
| 0:07–0:12 | The row shows **Extracting**, then **Ready for review**                   | "Gemini reads it in the background."              |
| 0:12–0:20 | Click the row. Slowly move the pointer down the **Match** column: *Supplier SKU 100%*, *MPN*, *Name* | "Supplier, bill number and all eight lines are read and matched to our parts: by supplier code, manufacturer number, or name." |
| 0:20–0:23 | Choose **Receive into location → Main store / Shelf A**                   | "I check it and pick where it goes."              |
| 0:23–0:26 | Click **Create order and receive**. The green "Bill received" toast appears | "One click."                                      |
| 0:26–0:30 | Click **View purchase order** (status *Complete*), then switch to Tab 1 and refresh: **1700** | "Purchase order created, stock received."         |

**Timing tips**

- Gemini usually takes 5–15 seconds. Keep recording and cut the wait in
  editing (or speed it up 4×). Don't fake the result.
- If a line is yellow or red, that's a good thing to show: pause on it, pick
  the right part from the dropdown, and say "anything uncertain is
  highlighted for a human to check."
- Optional extra 3 seconds at the end: upload the same photo again and show
  "This file has already been uploaded".

## The 4 best screenshots

Take them during the dry run, at 1440×900, with the superuser banner closed.

1. **Review screen (hero image).** The sample bill open on Scanned Bills, all
   eight lines visible with the Read and Match columns. This is the core of
   the product: AI output, matched parts and confidence on one screen. Use it
   at the top of the README and as the main LinkedIn image.
2. **Photo next to extraction.** Your phone photo of the printed bill on the
   left and the review table on the right, as one image (place them side by
   side in any image editor). This is the most persuasive image for LinkedIn,
   because people see a crumpled photo become structured data.
3. **The purchase order in InvenTree.** The order detail page: supplier
   Brightline Components, supplier reference BRL-INV-24817, status Complete,
   eight lines with quantities and prices. This proves real integration with
   InvenTree's own models, not a mock-up.
4. **Stock received.** The Resistor 10k 0603 part on its **Stock** tab, with
   the new stock item of 500 in Main store / Shelf A next to the original 1200.
   This closes the story: a bill photo became stock on the shelf.

For the README, put image 1 at the top. Images 3 and 4 go in a "From bill to
stock" section, and the architecture diagram is already in the README. For
LinkedIn, post 2 → 1 → 3 → 4 as a carousel.

Save README images to `docs/screenshots/` (committed). Keep any photo of a
real supplier bill out of the repo: only use the fictional demo bill in
public images.
