# Contributing to inventree-bill-scanner

Thanks for your interest! Bug reports, ideas, documentation fixes and code are
all welcome. If you're unsure where to start, open an issue and ask.

By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
Please report security problems privately, as described in
[SECURITY.md](SECURITY.md), and not in a public issue.

## Contents

- [Development setup](#development-setup)
- [Running the tests](#running-the-tests)
- [Lint and formatting](#lint-and-formatting)
- [Working on the panel (frontend)](#working-on-the-panel-frontend)
- [Branches and commits](#branches-and-commits)
- [Opening a pull request](#opening-a-pull-request)
- [What a good pull request includes](#what-a-good-pull-request-includes)

## Development setup

The plugin runs inside InvenTree, so you need an InvenTree source checkout
next to this repository. The `dev/` scripts keep all data (SQLite database,
media, config) in `.dev/` here and never write to the InvenTree tree.

```text
parent/
├── InvenTree/                 # https://github.com/inventree/InvenTree
└── inventree-bill-scanner/    # this repository
```

You need Python 3.12, Node.js 24 with Yarn 1, and git.

```bash
git clone https://github.com/inventree/InvenTree.git
git clone https://github.com/nisha-karithikeyan/inventree-bill-scanner.git
cd inventree-bill-scanner

# Use the InvenTree commit CI tests against (INVENTREE_REF in .github/workflows/ci.yml)
git -C ../InvenTree checkout 800cbe0d30687124aaeb143dbca6e04c64c7cffd

python3.12 -m venv .venv
.venv/bin/pip install -r ../InvenTree/src/backend/requirements.txt \
                      -r ../InvenTree/src/backend/requirements-dev.txt
.venv/bin/pip install -e ".[dev]"

dev/setup.sh      # migrate, enable the plugin, create a local admin/admin user
dev/demo.sh       # optional: demo supplier, parts with stock and a sample bill
```

Then run these, each in its own terminal:

```bash
dev/server.sh     # Django on http://localhost:8000
dev/worker.sh     # background worker (Gemini calls, retries)
dev/ui.sh         # InvenTree's React UI on http://localhost:5173
```

Set `INVENTREE_SRC=/path/to/InvenTree` if your checkout lives somewhere else.

Other helpers:

- `dev/demo.sh --fresh` moves the dev database and media to
  `.dev/backup/<time>/` and starts from an empty instance.
- `dev/seed_demo.sh` creates already-extracted demo bills from canned replies,
  so you can see the screens without an API key.
- `node dev/screenshots.mjs` recaptures `docs/screenshots/` from a running dev
  instance seeded with `dev/seed_demo.sh`.

You only need a Gemini API key to try real extraction. None of the tests use
one. Enter a key only in the plugin settings in the UI, never in code, config
files or commits.

## Running the tests

```bash
dev/test.sh                                   # backend, inside InvenTree's test runner
COVERAGE=1 dev/test.sh                        # with a coverage report
dev/test.sh bill_scanner.tests.test_matching  # one module
.venv/bin/python -m unittest discover eval    # eval scorer

cd frontend
yarn install
yarn typecheck
yarn test
```

The backend suite mocks every HTTP call to Gemini, so it is free and works
offline. Coverage of `bill_scanner/` is currently 100%; please keep new code
covered.

`eval/run.sh` is different: it sends real bills to Gemini and costs API
quota. It is for measuring accuracy, not for CI. See
[eval/README.md](eval/README.md).

## Lint and formatting

Python uses [Ruff](https://docs.astral.sh/ruff/), configured in
`pyproject.toml` to match InvenTree's own style (single quotes, Google-style
docstrings, 88 columns).

```bash
.venv/bin/ruff check .
.venv/bin/ruff format .
```

TypeScript is checked with `yarn typecheck` (strict mode). Keep the existing
style: two-space indentation and single quotes. `.editorconfig` sets
indentation and line endings for most editors.

## Working on the panel (frontend)

The React panel lives in `frontend/src/` and is built into
`bill_scanner/static/BillScanner.js`. The built file is committed, so that
`pip install` works without Node.

```bash
cd frontend
yarn build    # type-checks, then rebuilds bill_scanner/static/
```

If you change anything in `frontend/src/`, run `yarn build` and commit the
updated files in `bill_scanner/static/`. React and Mantine come from
InvenTree at runtime (see `vite.config.ts`). Do not bundle your own copies.

## Branches and commits

- Branch from `main` and give the branch a short, descriptive name with a
  type prefix, for example `feat/pack-quantities`, `fix/retry-timeout` or
  `docs/eval-guide`.
- Write commit messages with
  [Conventional Commits](https://www.conventionalcommits.org/):

  ```text
  <type>(optional scope): <summary in the imperative, lower case>
  ```

  | Type       | Use for                                       |
  | ---------- | --------------------------------------------- |
  | `feat`     | A new feature                                 |
  | `fix`      | A bug fix                                     |
  | `docs`     | Documentation only                            |
  | `test`     | Adding or fixing tests                        |
  | `refactor` | Code change that neither fixes nor adds       |
  | `perf`     | Performance improvement                       |
  | `build`    | Dependencies or packaging                     |
  | `ci`       | GitHub Actions                                |
  | `chore`    | Anything else that is not user-facing         |

  Examples: `fix(matching): ignore one-letter tokens in name scores`,
  `feat(ui): show the bill total next to the line sum`.
  Mark breaking changes with `!` (`feat!: ...`) and explain them in the body.
- Keep each commit focused. Small pull requests are reviewed faster.

## Opening a pull request

1. For anything larger than a small fix, open an issue first, so we can agree
   on the approach before you spend time on it.
2. Fork the repository and create your branch.
3. Make your change, with tests and docs.
4. Run lint and all tests locally (see above).
5. Push and open a pull request against `main`. The template has a checklist.
6. CI runs ruff, the backend tests and the frontend checks. All must pass.
7. A maintainer reviews the PR. Expect questions and small requests; that's
   normal and not a rejection.

## What a good pull request includes

- **Tests.** A bug fix starts with a test that fails without the fix. A
  feature has tests for the normal case and the edge cases. Matching changes
  should include realistic descriptions, because fuzzy scoring has surprising
  worst cases.
- **Docs.** Update the README, `docs/` or `eval/README.md` when behaviour,
  settings or the API change.
- **A changelog entry.** Add a line to the **Unreleased** section of
  [CHANGELOG.md](CHANGELOG.md) under *Added*, *Changed*, *Fixed* or
  *Security*.
- **Migrations.** If you change a model, add the migration (run
  `makemigrations bill_scanner` through `manage.py`, with the environment from
  `dev/env.sh`).
- **No secrets or private data.** No API keys, real bills, or real supplier
  names and prices, including in tests, fixtures and screenshots. Use fictional
  data like `dev/demo.py` does.
- **A short description** of what changed, why, and how you tested it.

Thank you for helping!
