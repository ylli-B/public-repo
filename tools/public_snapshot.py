"""Build the public portfolio snapshot from an explicit allow-list.

Design rule: **allow-list, never deny-list.** A deny-list leaks the first time
someone adds a file nobody thought to exclude. Nothing reaches the public repo
unless a path pattern here says it may, and even then it must survive the
scanner in `leak_guard`.

What the public repo is for: showing that this person can design a data
platform, enforce point-in-time correctness, and run agentic development with
real governance. What it is emphatically not for: publishing anything that
reveals a live edge, a model parameter, a bankroll, or a result.

Usage:
    python -m tools.public_snapshot --check     # guard only, used by CI
    python -m tools.public_snapshot --out build/public
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Paths that MAY be published. Anything not matched here is excluded.
#
# Deliberately absent, and why:
#   AGENTS.md              names data providers, endpoints and market findings
#   ingest/**/catalog.py   reveals exactly which feeds we pull
#   src/nfl_edge/sportsdataio.py   names the vendor integration
#   tests/unit/test_{alerts,bankroll,optimizer,contests}.py
#                          assert real thresholds, payouts and roster rules
#   tests/leakage/test_{nfl_rf,score_rf}_pit.py, test_pit_asof.py
#                          import private model code and name its features
#   pyproject.toml, .github/workflows/ci.yml
#                          describe the private tree; public versions are
#                          rendered from docs/public/ via PUBLIC_RENDERS
ALLOW = [
    # shared platform: generic infrastructure, no domain knowledge
    "src/evmax/**",
    "src/nfl_edge/__init__.py",
    "src/nfl_edge/as_of.py",
    # the guarantees themselves — synthetic data only, nothing domain-specific
    "tests/conftest.py",
    "tests/leakage/test_silver_pit.py",
    "tests/unit/test_staking.py",
    "tests/unit/test_platform_boundaries.py",
    "tests/unit/test_leak_guard.py",
    "tests/unit/test_backup_state.py",
    # the machinery that keeps this snapshot safe
    "tools/public_snapshot.py",
    "tools/leak_guard.py",
    "tools/backup_state.py",
    "tools/setup_repo_policy.py",
    # engineering practice
    ".github/pull_request_template.md",
    ".github/CODEOWNERS",
    "docs/architecture/**",
    "docs/governance.md",
    "docs/public-portfolio.md",
    "CONTRIBUTING.md",
    ".gitignore",
    ".env.example",
]

# Files written specifically for the public repo, copied to where a reader
# expects them. They are scanned like everything else.
PUBLIC_RENDERS = {
    "docs/public/README_PUBLIC.md": "README.md",
    "docs/public/pyproject.toml": "pyproject.toml",
    "docs/public/ci.yml": ".github/workflows/ci.yml",
}

# Top-level packages that exist only in this repository. A published file that
# imports one of them must find the imported module published too, or a reader
# who clones the snapshot gets an ImportError on the first test run.
FIRST_PARTY = ("evmax", "nfl_edge", "ml", "ingest", "apps", "tools", "spark")

# Belt and braces: even inside ALLOW, these never ship.
NEVER = [
    "**/.env",
    "**/*.joblib",
    "**/*.parquet",
    "**/*.pkl",
    "**/*.sqlite",
    "data/**",
    "ml/artifacts/**",
    "state/**",
    "**/findings*.md",
    "**/dfs-ops.md",
    "**/RESULTS*.md",
    "**/*seed-data.ts",
]


def _matches(rel: str, patterns: list[str]) -> bool:
    rel = rel.replace("\\", "/")
    for pat in patterns:
        if fnmatch.fnmatch(rel, pat):
            return True
        # allow "dir/**" to match the directory's own files at any depth
        if pat.endswith("/**") and rel.startswith(pat[:-3] + "/"):
            return True
    return False


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def selected() -> list[str]:
    return [f for f in tracked_files()
            if _matches(f, ALLOW) and not _matches(f, NEVER)]


def _is_module_file(module: str, paths: set[str]) -> bool:
    stem = module.replace(".", "/")
    return any(base + suffix in paths
               for base in (stem, "src/" + stem)
               for suffix in (".py", "/__init__.py"))


def _resolves(module: str, paths: set[str]) -> bool:
    """True if a published file or package directory provides ``module``."""
    if _is_module_file(module, paths):
        return True
    stem = module.replace(".", "/")
    # namespace package: a directory with no __init__.py
    return any(p.startswith((stem + "/", "src/" + stem + "/")) for p in paths)


def unresolved_imports(published: dict[str, str]) -> list[str]:
    """First-party imports in published Python that the snapshot cannot satisfy.

    ``published`` maps each published path to its source text.
    """
    paths = set(published)
    problems = []
    for rel, source in sorted(published.items()):
        if not rel.endswith(".py"):
            continue
        missing: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                missing.update(a.name for a in node.names
                               if a.name.split(".")[0] in FIRST_PARTY
                               and not _resolves(a.name, paths))
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                if node.module.split(".")[0] not in FIRST_PARTY:
                    continue
                if not _resolves(node.module, paths):
                    missing.add(node.module)
                elif not _is_module_file(node.module, paths):
                    # a namespace package has no attributes, so every imported
                    # name must be a published submodule
                    missing.update(f"{node.module}.{a.name}" for a in node.names
                                   if not _resolves(f"{node.module}.{a.name}", paths))
        problems += [f"{rel}: imports {m}, which is not published" for m in sorted(missing)]
    return problems


def _render_sources() -> dict[str, str]:
    """PUBLIC_RENDERS whose source exists. Inside the published snapshot the
    sources are absent because they have already been rendered into place."""
    return {src: dst for src, dst in PUBLIC_RENDERS.items() if (ROOT / src).exists()}


def _published_sources(files: list[str]) -> dict[str, str]:
    out = {rel: (ROOT / rel).read_text(encoding="utf-8") for rel in files}
    for src, dst in _render_sources().items():
        out[dst] = (ROOT / src).read_text(encoding="utf-8")
    return out


def problems() -> list[str]:
    """Everything that must be empty before the snapshot may be built."""
    from tools.leak_guard import scan_paths

    files = selected()
    found = [f"LEAK  {f}" for f in
             scan_paths([ROOT / f for f in files] + [ROOT / s for s in _render_sources()])]
    found += [f"BROKEN  {p}" for p in unresolved_imports(_published_sources(files))]
    return found


def build(out_dir: Path) -> list[str]:
    found = problems()
    if found:
        for f in found:
            print(f, file=sys.stderr)
        raise SystemExit(f"refusing to build: {len(found)} problem(s)")

    files = selected()
    if out_dir.exists():
        shutil.rmtree(out_dir)
    for rel in files:
        dst = out_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dst)
    for src, rel in PUBLIC_RENDERS.items():
        dst = out_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / src, dst)
    print(f"staged {len(files) + len(PUBLIC_RENDERS)} files into {out_dir}")
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="build/public")
    ap.add_argument("--check", action="store_true",
                    help="scan the selection for leaks without writing anything")
    ap.add_argument("--list", action="store_true", help="print the selected files")
    args = ap.parse_args()

    if args.list:
        for f in selected():
            print(f)
        for src, dst in PUBLIC_RENDERS.items():
            print(f"{dst}  (from {src})")
        return 0
    if args.check:
        found = problems()
        for f in found:
            print(f, file=sys.stderr)
        n = len(selected()) + len(_render_sources())
        print(f"checked {n} publishable files, {len(found)} finding(s)")
        return 1 if found else 0

    build(ROOT / args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
