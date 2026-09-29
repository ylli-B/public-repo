"""Architecture rules, enforced rather than described.

The platform must not know about any sport. Once a domain name leaks into
`evmax`, the "shared infrastructure" claim quietly stops being true, and the
next domain inherits MLB's assumptions.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLATFORM = ROOT / "src" / "evmax"
DOMAIN_WORDS = ("mlb", "nfl", "dfs", "draftkings", "fanduel", "slate", "batting")


def _platform_modules() -> list[Path]:
    return sorted(p for p in PLATFORM.rglob("*.py") if p.name != "__init__.py")


def test_platform_package_exists():
    assert _platform_modules(), "expected shared modules under src/evmax"


@pytest.mark.parametrize("mod", _platform_modules(), ids=lambda p: p.name)
def test_platform_never_imports_a_domain(mod: Path):
    tree = ast.parse(mod.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    for name in imported:
        assert not name.startswith(("ml.", "ingest.")), \
            f"{mod.name} imports domain module {name}"


@pytest.mark.parametrize("mod", _platform_modules(), ids=lambda p: p.name)
def test_platform_identifiers_stay_domain_neutral(mod: Path):
    """Docstrings may mention history; code must not hardcode a sport."""
    tree = ast.parse(mod.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.append(node.name)
        elif isinstance(node, ast.Name):
            names.append(node.id)
    offenders = [n for n in names if any(w in n.lower() for w in DOMAIN_WORDS)]
    assert not offenders, f"{mod.name} has domain-specific names: {sorted(set(offenders))}"
