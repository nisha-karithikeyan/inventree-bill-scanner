# Accuracy evaluation

Measures how well the plugin reads real bills and matches their lines to your
parts. It runs the plugin's own code against the InvenTree database that
`dev/env.sh` points at (the dev instance in `.dev/` by default).

## Add bills

Put each bill in `eval/bills/`, with its ground truth next to it under the
same name:

```text
eval/bills/
├── acme-2026-0412.jpg
├── acme-2026-0412.json
├── demo-des-2057.pdf
└── demo-des-2057.json
```

Everything in `eval/bills/` and `eval/results/` is gitignored. Real bills and
the numbers on them never get committed.

Copy [template.json](template.json) to start a ground-truth file:

| Field               | Required | Meaning                                                              |
| ------------------- | -------- | -------------------------------------------------------------------- |
| `supplier_name`     | yes      | Supplier name as printed on the bill                                 |
| `expected_supplier` | no       | Name of the InvenTree company the bill should be linked to           |
| `bill_number`       | yes      | Bill or invoice number as printed                                    |
| `bill_date`         | no       | `YYYY-MM-DD`, or `null` if the bill has no date                      |
| `currency`          | no       | ISO code such as `USD`                                               |
| `lines`             | yes      | Every purchased line, in any order                                   |
| `lines[].description` | yes    | Description as printed                                               |
| `lines[].sku`       | no       | Supplier item code, if printed (helps pair lines)                    |
| `lines[].quantity`  | yes      | Quantity                                                             |
| `lines[].unit_price`| no       | Unit price before tax, or `null` if not printed                      |
| `lines[].expected_part` | no   | IPN or exact name of the part it should match, or `null` for "no part" |

Leave out a field to skip it in the score. Do not list tax, shipping or
discount summary rows: the plugin is told to ignore them, and extracting
one counts as an extra line.

## Run

```bash
eval/run.sh --check        # validate files and expected parts; no API call
eval/run.sh                # send every bill to Gemini and score it
eval/run.sh --only acme    # only bills whose file name contains "acme"
```

Only `eval/run.sh` without `--check` calls Gemini: one call per bill, plus
retries. The test suites never call it. The key, model and thresholds come from
the plugin settings, so set the key in the UI first (see
[docs/FIRST_TEST.md](../docs/FIRST_TEST.md)).

## What is measured

Each bill takes the same path as an upload in the panel:

1. `BillUploadSerializer` checks the size and real file type.
2. `tasks.extract_bill`, the function the background worker runs, sends the
   file to Gemini, parses the reply with `parse_extraction`, saves the lines and
   runs `match_bill`.
3. Transient failures are retried with the plugin's own backoff.

The rows are written inside a database transaction that is rolled back, and
the files go to a temporary media folder, so nothing is left in InvenTree.

[scoring.py](scoring.py) then compares the stored result with the ground
truth. It deliberately has its own normalisation, so a bug in the plugin
cannot hide itself in the score.

| Section         | Numbers                                                                 |
| --------------- | ----------------------------------------------------------------------- |
| Header fields   | Accuracy of supplier name, bill number, date, currency; supplier company match |
| Line items      | Recall, precision, and accuracy of description, quantity and unit price; share of lines fully correct |
| Part matching   | Share of lines matched to the expected part, split by match method      |
| Confidence      | Average read and match confidence; read confidence on right vs wrong lines; share of wrong lines the panel highlights |
| Failures        | Every wrong field or line with the expected and actual value            |

Comparison rules: supplier names ignore case, punctuation and suffixes such as
Ltd (fuzzy score ≥ 90). Bill numbers ignore case and punctuation. Descriptions
need a fuzzy score ≥ 85. Quantities must be exact. Unit prices may differ by
0.5% or one cent.

Results go to `eval/results/report.md` (summary) and
`eval/results/extracted.json` (raw extracted data for each bill).

## Tests

```bash
.venv/bin/python -m unittest discover eval
```
