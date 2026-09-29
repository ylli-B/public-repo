"""The guard that stands between a private edge and a public repo.

If these tests are weak, everything downstream of them is theatre.
"""

from __future__ import annotations

import pytest

from tools import public_snapshot
from tools.leak_guard import scan_text


# Every fixture below is a fake that exists to trip the scanner, so each line
# carries the reviewed escape hatch. Without it this file would fail its own
# guard — which is the correct default, and exactly what the hatch is for.
@pytest.mark.parametrize("payload", [
    "TWILIO_ACCOUNT_SID = 'ACdeadbeefdeadbeefdeadbeefdeadbeef'",  # leak-guard: allow
    "key = 'AKIAIOSFODNN7EXAMPLE'",  # leak-guard: allow
    "token = 'ghp_abcdefghijklmnopqrstuvwxyz0123456789'",  # leak-guard: allow
    "DATABASE_URL = 'postgresql://user:hunter2@db.example.com:5432/prod'",  # leak-guard: allow
    "-----BEGIN RSA PRIVATE KEY-----",  # leak-guard: allow
    "apify = 'apify_api_abcdefghijklmnopqrstuvwxyz123'",  # leak-guard: allow
])
def test_secrets_are_caught(payload):
    assert scan_text(payload, "f.py")


@pytest.mark.parametrize("payload", [
    "SPORTSDATAIO_API_KEY=",
    "api_key = 'REPLACE_ME'",
    "password = '<your-password>'",
    "token = 'example'",
    "# how to set an api_key in your .env",
])
def test_placeholders_are_not_flagged(payload):
    assert scan_text(payload, "f.py", edges=False) == []


@pytest.mark.parametrize("payload", [
    "DATABASE_URL=postgresql://nfl_edge:nfl_edge_dev@localhost:5433/nfl_edge",
    "postgresql://mlb_edge:mlb_edge_dev@127.0.0.1:5434/mlb_edge",
    "postgresql://user:pass@postgres:5432/db",
])
def test_local_container_credentials_are_not_secrets(payload):
    """A password to a throwaway local Docker database is noise, not a leak."""
    assert scan_text(payload, "docker-compose.yml", edges=False) == []


def test_remote_database_credentials_are_still_caught():
    url = "postgresql://admin:s3cret@prod.example.com:5432/live"  # leak-guard: allow
    assert scan_text(url, "f.py")


# Fixtures use invented numbers on purpose: a test that echoes our real
# thresholds would itself become the leak it is meant to prevent.
@pytest.mark.parametrize("payload", [
    "model vs sharp field ROI: +99.9%",  # leak-guard: allow
    "win_rate = 0.123",  # leak-guard: allow
    "WIN_SHARP, WIN_NAIVE = 0.111, 0.222",  # leak-guard: allow
    "BACKTEST_PROJ_MEAN = 999.9",  # leak-guard: allow
    '"bankroll": 1234.0',  # leak-guard: allow
    "kelly_fraction: 0.99",  # leak-guard: allow
    "max_per_lineup = 777",  # leak-guard: allow
])
def test_edge_revealing_numbers_are_caught_for_public(payload):
    assert scan_text(payload, "f.md")


def test_edge_rules_do_not_fire_inside_the_private_repo():
    """Those numbers are the product; they are only a problem when published."""
    assert scan_text("win_rate = 0.123", "f.py", edges=False) == []  # leak-guard: allow


def test_allow_comment_provides_a_reviewed_escape_hatch():
    line = "win_rate = 0.123  # leak-guard: allow"
    assert scan_text(line, "f.py") == []


def test_public_allow_list_excludes_the_dangerous_paths():
    """Spot-check the selection logic rather than the live git tree."""
    for path in ("ml/mlb/dfs_alpha_test.py", "docs/ml/findings-mlb.md",
                 "ml/artifacts/mlb/gameday/bankroll.json", ".env",
                 "data/bronze/sport=mlb/x.json", "state/mlb/results_ledger.csv",
                 "apps/tracker/src/lib/mlb-seed-data.ts"):
        assert not public_snapshot._matches(path, public_snapshot.ALLOW) or \
            public_snapshot._matches(path, public_snapshot.NEVER), \
            f"{path} would be published"


def test_public_allow_list_includes_the_portfolio_surface():
    for path in ("src/evmax/staking.py", "src/nfl_edge/as_of.py",
                 "tests/leakage/test_silver_pit.py", "docs/governance.md",
                 "docs/architecture/overview.md"):
        assert public_snapshot._matches(path, public_snapshot.ALLOW), f"{path} missing"


def test_public_repo_gets_its_own_readme_pyproject_and_ci():
    """The private versions describe files the public repo does not have."""
    rendered = set(public_snapshot.PUBLIC_RENDERS.values())
    assert {"README.md", "pyproject.toml", ".github/workflows/ci.yml"} <= rendered
    for private in ("pyproject.toml", ".github/workflows/ci.yml"):
        assert not public_snapshot._matches(private, public_snapshot.ALLOW)


def test_published_snapshot_is_self_contained():
    """Regression: published leakage tests imported unpublished ml.* modules,
    so the public repo failed with ImportError the moment a reader ran pytest."""
    sources = public_snapshot._published_sources(public_snapshot.selected())
    assert public_snapshot.unresolved_imports(sources) == []


def test_unpublished_first_party_import_is_reported():
    sources = {
        "tests/leakage/test_x.py": "from ml.nfl.features import FEATURE_COLUMNS\n",
        "src/evmax/staking.py": "",
    }
    assert public_snapshot.unresolved_imports(sources) == [
        "tests/leakage/test_x.py: imports ml.nfl.features, which is not published",
    ]


@pytest.mark.parametrize("source", [
    "import pandas as pd\nfrom httpx import Client\n",       # third party
    "from evmax.staking import kelly\n",                      # module is published
    "from tools import public_snapshot\n",                    # submodule of a namespace pkg
    "from nfl_edge.as_of import assert_no_future_leakage\n",
])
def test_resolvable_imports_are_not_reported(source):
    sources = {
        "tests/unit/test_y.py": source,
        "src/evmax/staking.py": "",
        "src/nfl_edge/as_of.py": "",
        "tools/public_snapshot.py": "",
    }
    assert public_snapshot.unresolved_imports(sources) == []


@pytest.mark.parametrize("path", [
    "AGENTS.md",                          # names providers, endpoints, findings
    "ingest/discoverylab/catalog.py",     # reveals which feeds we pull
    "src/nfl_edge/sportsdataio.py",       # names the vendor integration
    "tests/unit/test_alerts.py",          # asserts the real slate threshold
    "tests/unit/test_bankroll.py",        # asserts real payouts and win rates
    "tests/unit/test_optimizer.py",       # encodes roster and cap rules
    "docs/ml/dfs-ops.md",
])
def test_domain_revealing_paths_are_not_publishable(path):
    assert not public_snapshot._matches(path, public_snapshot.ALLOW), \
        f"{path} would be published"


def test_never_list_beats_allow_list():
    assert public_snapshot._matches("tests/unit/x.joblib", public_snapshot.NEVER)
