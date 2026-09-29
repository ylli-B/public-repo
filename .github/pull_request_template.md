## What and why

<!-- One paragraph. What changes, and what problem it solves. -->

## Risk

- [ ] Touches a **money path** (entry, staking, projections, ledger, alerts)
      → I have shown a dry run in the description below
- [ ] Changes model features or training data
- [ ] Changes anything published to the public snapshot

## Checks

- [ ] A test fails without this change
- [ ] `ruff check .` clean
- [ ] `pytest -q tests` green, including `tests/leakage`
- [ ] No secret, key, or real credential added anywhere
- [ ] No edge-revealing number added to a file that can be published

## Verification

<!-- What you actually ran, and what it printed. "CI is green" is not enough
     for a money-path change: show the dry run. -->
