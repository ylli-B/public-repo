# EV Max Platform — public engineering snapshot

A platform for building **expected-value maximising** systems: ingest data with
point-in-time correctness, research whether an edge exists, and — only if it
does — run it with disciplined staking and monitoring.

Sports betting and daily fantasy are the first domain. The interesting part is
not the sport; it is the machinery for deciding, honestly, whether a claimed
edge is real.

> This repository is an automatically generated snapshot of a private codebase.
> It contains architecture, platform code, tests, and engineering practice. It
> deliberately contains **no** strategies, model parameters, results, or data.
> The generator uses an allow-list and a scanner that fails the build if an
> edge-revealing value appears. See `tools/public_snapshot.py`.

## What this demonstrates

**Point-in-time discipline.** The most common way a backtest lies is by letting
a feature row see something that did not exist yet. Every feature carries an
`as_of` timestamp, joins are strict backward as-of joins, and the guarantee is
enforced by a dedicated `tests/leakage/` suite rather than by care.

**A survivorship bug, found and fixed.** An early feature join attached
same-day statistics, which silently dropped every player who did not appear.
That hands the backtest perfect foresight about who plays. Switching to an
as-of join kept non-appearing entities in the pool and changed the measured
result materially — in one configuration the apparent edge inverted.

**Negative results are results.** A large part of this work concluded that a
market was efficient and that a previously claimed profit was sampling noise
inside its own confidence interval. That conclusion was written down and the
line of work was closed. A research platform that cannot kill its own ideas is
a very expensive way to lose money.

**Governance for agent-written code.** This codebase is largely written by AI
agents. The response is not to trust them; it is to make the invariants
machine-checked: secret scanning on every push, leakage tests that cannot be
weakened to make a build pass, an architecture test that parses the AST to prove
the shared platform never imports a domain, and a test suite that blocks network
sockets outright after a test once delivered a real notification.

## Architecture

```
src/evmax/        shared platform: notification, run logging, Kelly staking
                  (must not import a domain; enforced by test)
src/nfl_edge/     point-in-time as-of helpers
tests/unit/       pure and fast, no network, no database
tests/leakage/    point-in-time correctness on synthetic data
tools/            leak guard, public snapshot, state backup, repo policy
docs/             governance, architecture, how this snapshot is built

kept private      ingestion, dbt medallion models (bronze -> silver -> gold),
                  features, models, and per-domain operations
```

Data follows a medallion pattern: immutable raw payloads with manifests, typed
point-in-time entities, then leakage-tested marts. The private repository runs
further leakage suites against its real models; the one published here
exercises the same slowly-changing-dimension and prior-games-only contracts on
synthetic data.

## Running it

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
ruff check .
pytest -q tests
```

The suite blocks network sockets, so it needs no credentials and no database.

## Engineering practice

| Concern | Mechanism |
|---|---|
| Credentials | Allow-list scanner on every push; `.env` never committed |
| Look-ahead bias | Strict as-of joins with a dedicated test suite |
| Architecture drift | AST test asserting the platform imports no domain |
| Flaky or dishonest tests | Sockets blocked suite-wide |
| Lost operational records | Versioned state backup plus offsite archive |
| Review bottleneck | Required PRs with auto-merge on green; risky paths labelled |

## Reading order

1. `docs/governance.md` — the rules and why each exists
2. `docs/architecture/overview.md` — layers, medallion contract, research lifecycle
3. `tests/leakage/test_silver_pit.py` — the point-in-time guarantees that matter most
4. `src/evmax/staking.py` — turning an edge into a stake without going broke
5. `tools/public_snapshot.py` and `tools/leak_guard.py` — how this snapshot stays
   safe to publish and runnable on its own

## Author

William Machado — [linkedin.com/in/billymachado](https://www.linkedin.com/in/billymachado/)
