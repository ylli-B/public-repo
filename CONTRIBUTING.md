# Contributing

Full policy: [docs/governance.md](docs/governance.md). This is the short version
you need to actually get a change in.

## Setup

```bash
python -m pip install -e ".[dev]"
cp .env.example .env          # then fill in the values you need
```

## The loop

```bash
git switch -c feat/short-description

# ... make the change, with a test that fails without it ...

ruff check .
pytest -q tests
python -m tools.leak_guard --secrets-only
python -m tools.public_snapshot --check

git commit -m "area: what changed and why"
git push -u origin HEAD
```

**That is the whole flow.** Pushing the branch opens the pull request, runs CI,
and merges it when everything is green. Do not open, review, or merge PRs by
hand.

If the diff touches a money path — entry, staking, projections, the ledger, or
notifications — take extra care and show a dry run in the PR description, not
just "CI is green".

## Before you push, check yourself

- Does a test fail without this change?
- Could this let a model see the future? Add a case in `tests/leakage/`.
- Does it print, log, or commit anything derived from a real key?
- Would it change what gets entered or how much is staked? Label it.
- Is the new code in the right layer? Shared logic goes in `src/evmax/` and may
  not import a domain.

## Commit messages

`area: imperative summary`, then a body explaining *why* if it is not obvious.

```
dfs: seat-grab alert via late swap

DK Classic is late swap, so entering hours early costs no lineup quality.
```

## Running the operational bits

```bash
python -m ml.mlb.dfs_daily --dry-run     # compose alerts without sending
python -m tools.backup_state --verify    # is the track record backed up?
```
