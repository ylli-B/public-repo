# Architecture overview

The repository is organised around one idea: **find and exploit expected value,
wherever it is.** Sports are the first domain because the data is cheap and the
feedback loop is short, not because the platform is about sports.

## Layers

```
                 ┌──────────────────────────────────────────┐
   domains       │  ml/mlb   ml/gameday   (future domains)   │
                 │  features, models, operations             │
                 └───────────────────┬──────────────────────┘
                                     │  depends on
                 ┌───────────────────▼──────────────────────┐
   platform      │  src/evmax                                │
                 │  notify · runlog · staking                │
                 └───────────────────┬──────────────────────┘
                                     │
                 ┌───────────────────▼──────────────────────┐
   data plane    │  ingest -> bronze -> dbt silver -> gold   │
                 └──────────────────────────────────────────┘
```

The arrow only points one way. `src/evmax` may not import a domain, and
`tests/unit/test_platform_boundaries.py` parses the AST to prove it rather than
relying on discipline.

## Medallion data plane

| Layer | Contract |
|---|---|
| Bronze | Immutable raw payloads plus manifests. Never edited, only appended. |
| Silver | Typed entities carrying `as_of_ts`. One row per entity per point in time. |
| Gold | Feature and label marts, leakage-tested, joined only on prior information. |

Every feature row carries `as_of_ts`. A row describing an event may only see
information that existed strictly before that event's clock: kickoff for
NFL, first pitch for MLB, contest lock for DFS.

## Research lifecycle

A domain earns production only by surviving the same sequence:

1. **Understand the data** before modelling it, including how stale each feed is.
2. **Build a point-in-time panel.** If this step is wrong nothing after it means
   anything.
3. **Test for an edge against the right benchmark** — the market price or the
   field, never a naive baseline that nobody actually plays.
4. **Convert the edge into money terms**: win rate against the real payout, with
   real fees, not points above a baseline.
5. **Size it** with fractional Kelly against a dedicated bankroll.
6. **Operate it**: scheduled alerts, a graded ledger, and backed-up state.
7. **Kill it** and write down why when the edge is not there.

Step 7 has fired more often than step 6, which is the expected and healthy ratio.

## Operational shape

Scheduled jobs poll for events, build recommendations only when the inputs
actually exist, and notify a human who executes manually. There is deliberately
no automated placement: it violates operator terms and concentrates
catastrophic-error risk.

State that represents the track record — the graded ledger, staking config — is
backed up to a versioned location and an offsite archive, because a research
result can be regenerated from bronze while a record of what was actually
entered cannot.
