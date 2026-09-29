# Public portfolio

The private repository is the product. The public repository is a hiring
artefact generated from it. It must be genuinely impressive and must never cost
us anything.

## The rule

**Allow-list, never deny-list.** A deny-list leaks the first time somebody adds
a file nobody thought to exclude. `tools/public_snapshot.py` starts from
nothing and admits only paths that match `ALLOW`, then removes anything matching
`NEVER`, then runs `tools/leak_guard.py` over the survivors and refuses to build
if anything trips.

**The snapshot must run on its own.** A reader's first move is `pip install`
and `pytest`. The build also refuses if any published Python file imports a
first-party module that is not published, so a test that reaches into private
domain code belongs in a separate, unpublished file. `README.md`,
`pyproject.toml` and the CI workflow are rendered from `docs/public/` because
the private versions describe files the public repo does not have.

## What is published, and what is not

| Published | Withheld |
|---|---|
| `src/evmax/` shared platform | All domain strategy code |
| `tests/` including the leakage suite | Any measured ROI, win rate, or threshold |
| `tools/` guard and snapshot machinery | Bankroll figures and staking config |
| Architecture and governance docs | `docs/ml/findings-*.md`, `dfs-ops.md` |
| `pyproject.toml`, CI config, `.env.example` | Any data, artifact, or model |

The withheld list is not squeamishness. A published threshold is a published
edge, and a published edge is worth nothing.

## Why the public version is still strong

It shows point-in-time rigour, a real survivorship bug caught and corrected,
the discipline to publish a negative result and close a line of work, and a
governance model for agent-written code. That is a better signal to a hiring
manager than a strategy they cannot verify anyway.

## Running it

```bash
python -m tools.public_snapshot --list     # what would ship
python -m tools.public_snapshot --check    # guard only; runs in CI
python -m tools.public_snapshot            # stage into build/public
```

## Publishing

CI runs `--check` on every push, so the guard is continuously monitored even
before anything is published.

To publish automatically, create an empty public repo and add a fine-grained
PAT with contents:write on it as the `PUBLIC_REPO_TOKEN` secret. The
`public-snapshot` workflow then force-pushes the staged snapshot on every merge
to `master`. Without the secret the workflow still runs the guard and skips the
push, which is the safe default.

## Before the first publish

Read the staged output rather than trusting the scanner:

```bash
python -m tools.public_snapshot && ls -R build/public
```

The scanner catches patterns. Only a human catches a paragraph that explains the
edge in prose.
