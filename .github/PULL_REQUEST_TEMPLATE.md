## What does this change?

<!-- A short summary, and why it is needed. -->

Closes #

## How was it tested?

<!-- Commands you ran, and any manual steps in the review panel. -->

## Checklist

- [ ] The PR title follows [Conventional Commits](https://www.conventionalcommits.org/) (for example `fix: keep manual matches after re-reading a bill`)
- [ ] New or changed behaviour has tests (`dev/test.sh`, `yarn test`, or `eval/test_scoring.py`)
- [ ] `ruff check .` and `ruff format --check .` pass
- [ ] Frontend: `yarn typecheck` and `yarn test` pass; if `frontend/src` changed, `yarn build` was run and `bill_scanner/static/` is committed
- [ ] Docs are updated (README, `docs/`, or `eval/README.md`) if behaviour or settings changed
- [ ] `CHANGELOG.md` has an entry under **Unreleased**
- [ ] A new migration is included if models changed (`makemigrations bill_scanner`)
- [ ] No API keys, real bills or private supplier data are included
