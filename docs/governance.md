# Engineering governance

This codebase is written almost entirely by AI agents and it moves real money.
Those two facts together are why the rules below are hard requirements rather
than aspirations. An agent has no memory of yesterday's outage and no instinct
that something feels wrong, so every guarantee has to be written down and
enforced by a machine.

## The four things that must never happen

| Must never happen | What prevents it |
|---|---|
| A credential reaches the remote | `tools/leak_guard.py` runs on every push and blocks the build |
| A model sees the future | `tests/leakage/` asserts strict as-of joins |
| An edge or result becomes public | Allow-list snapshot plus a second scan in `tools/public_snapshot.py` |
| The track record is lost | `tools/backup_state.py` copies records to `state/` and an offsite archive |

## Branch and review policy

`master` is protected. Nobody pushes to it directly, including the owner and
including agents.

**The owner never opens, reviews, or merges a pull request.** The only human
action in the loop is pushing a branch; everything after that is automated.

1. Work happens on a branch: `feat/`, `fix/`, `chore/`, or `docs/`.
2. Pushing the branch triggers **Auto PR**, which opens the pull request and
   writes the description from the commit. It does not merge anything.
3. **CI** runs on the push itself — secret scan, lint, unit tests, leakage
   tests, portfolio guard, dbt parse, web builds.
4. When CI finishes, **Auto-merge** re-reads every check on that exact commit
   and merges only if all of them completed green. The branch is deleted.

CI deliberately triggers on `push` for every branch rather than on
`pull_request`. Pull requests opened by a workflow using `GITHUB_TOKEN` do not
trigger further workflows, so a `pull_request`-only CI would leave automated PRs
sitting with no checks and auto-merge would never fire.

### What is actually enforced today (2026-08-10)

Steps 2 and 4 above describe the design. Parts of it are **not enforced by the
server** on this repository's plan, and one of them failed open.

#### The incident: a merge that outran its own CI

PR #4 merged to `master` at **23:19:15** with all nine of its checks still
running. The earliest completed at 23:19:16 and `Lint and tests` at 23:20:00 —
every check finished *after* the commit had already landed. It passed, but
nothing had verified that at merge time.

The cause is a misreading of `gh pr merge --auto`. It does not mean "merge when
CI passes"; it means "merge as soon as GitHub stops objecting". GitHub only
objects for checks that a **branch protection rule marks required**, and branch
protection needs GitHub Pro on a private repo. With no required checks there
was nothing to wait for, so `--auto` merged on the spot.

Merging now happens in `automerge.yml` on `workflow_run` after CI reports, and
it verifies independently, refusing on anything it cannot confirm:

- every check run on the head commit is `completed`
- every conclusion is `success`, `skipped` or `neutral`
- the CI run describes the commit that would actually be merged, not an older one
- the PR is not a draft

A test fails the build if any workflow reintroduces `gh pr merge --auto`.

#### Current state of each control

| Control | State |
|---|---|
| Auto PR opens the pull request | Working, once Actions were permitted to create PRs |
| CI runs and reports | Working |
| Merge waits for green | Working, **enforced by `automerge.yml`, not by the server** |
| **Native auto-merge** | **Unavailable.** `PATCH /repos` returns 200 for `allow_auto_merge` and silently leaves it false |
| **Branch protection / no direct push to `master`** | **Unavailable.** 403: "Upgrade to GitHub Pro or make this repository public" |

Two consequences follow from the last row, and they should be read plainly:

1. **A direct push to `master` still bypasses everything.** Nothing on the
   server prevents it. "Never commit to `master`" is a rule agents follow, not
   a wall they hit.
2. **The merge gate is only as trustworthy as the workflow implementing it.** A
   change to `automerge.yml` can weaken it, and that change would be gated by
   the very workflow it modifies.

Both are fixed by GitHub Pro (about $4/month) or by making the repository
public. Until then this is defence in depth without the outermost wall.

`python -m tools.setup_repo_policy --apply` reads the settings back after
writing them and exits non-zero while any of this is still true, so the gap
cannot quietly become invisible again.

### What counts as a money path

Anything that can change what gets entered, how much is staked, or what the
record says it earned:

- `ml/mlb/dfs_daily.py`, `dfs_gameday.py`, `dfs_bankroll.py`, `dfs_contests.py`
- `ml/mlb/dfs_panel.py` and anything feeding features into a live model
- `src/evmax/staking.py`, `src/evmax/notify.py`
- `state/**` and the results ledger

Changes here demand extra care: show a dry run in the PR description, and treat a
bug there as costing money rather than time.

## Testing standards

A change that alters behaviour ships with a test that would fail without it.

- **Unit tests** (`tests/unit/`) — pure, fast, no network, no database. The
  suite blocks sockets outright; an early version of the notification tests
  patched the wrong module and delivered a real push notification, which is
  exactly the class of accident that block prevents.
- **Leakage tests** (`tests/leakage/`) — point-in-time correctness. These are
  the most valuable tests in the repo because a leak does not crash anything.
  It quietly inflates a backtest and produces a model that loses money live.
- **Regression tests** — every bug that reaches production earns a test. The
  duplicate-player bug (one player in two roster slots, caused by two park rows
  normalising to the same team) is pinned by
  `tests/unit/test_optimizer.py::test_no_player_appears_twice`.

Do not test by re-running a research script and eyeballing a number. If the
correctness claim matters, encode it.

## Lint policy

`ruff check .` must be clean. Research scripts are exempt from cosmetic rules
only (line length, strict `zip`, unused loop variables) via `per-file-ignores`
in `pyproject.toml`. The production surface is never exempt.

## Secrets

- Real values live in `.env`, which is gitignored and has never been committed.
- `.env.example` carries key names with empty values, and nothing else.
- Local Docker credentials are not secrets; the scanner deliberately ignores
  `localhost` connection strings so the real signal is not buried in noise.
- A credential pasted into a chat window is a leaked credential. Rotate it.

## Architecture rules

`src/evmax/` is the shared platform. It must not import a domain, and its
identifiers must not mention one. This is enforced by
`tests/unit/test_platform_boundaries.py`, which parses the AST rather than
trusting a convention.

Domains (`ml/mlb/`, `ml/gameday/`, future non-sports work) depend on the
platform. The dependency never points the other way.

## Public exposure

The public repository is generated from an explicit allow-list, never a
deny-list, because a deny-list leaks the first time somebody adds a file nobody
thought to exclude. See [public-portfolio.md](./public-portfolio.md).

## For agents working in this repository

Read this before your first commit. Concretely:

- Never commit directly to `master`.
- Never add a secret, even temporarily, even in a test fixture.
- Never publish a number that reveals an edge.
- Never weaken a leakage test to make a build pass. If a leakage test fails,
  the model is wrong, not the test.
- Show a dry run in the PR description when you touch a money path.
- If you cannot make something safe, stop and say so rather than shipping it.
