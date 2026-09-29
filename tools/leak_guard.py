"""Scan files for secrets and for anything that would reveal a live edge.

Two different harms, one scanner:

  secrets   an API key, token or connection string that lets someone spend our
            money or read our data
  edge      a threshold, win rate, ROI or model parameter that tells a reader
            how to replicate the strategy, which destroys its value

The secret rules run over the whole repo on every push. The edge rules run only
over files staged for the public snapshot, because inside a private repo those
numbers are the entire point.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SECRET_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("twilio account sid", re.compile(r"\bAC[0-9a-fA-F]{32}\b")),
    ("twilio api/service sid", re.compile(r"\b(SK|MG|BN|BU)[0-9a-fA-F]{32}\b")),
    ("aws access key", re.compile(r"\bAKIA[0-9A-Z]{16,20}\b")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("slack token", re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}\b")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("postgres url with password",
     re.compile(r"postgres(?:ql)?://[^\s:'\"]+:[^\s@'\"]+@"
                r"(?!localhost|127\.0\.0\.1|postgres[:/]|mlb-postgres[:/]|db[:/])")),
    ("apify token", re.compile(r"\bapify_api_[A-Za-z0-9]{20,}\b")),
]

ASSIGNED_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|auth[_-]?token|secret|password|passwd|access[_-]?token)"
    r"\s*[:=]\s*['\"]([A-Za-z0-9_\-/+=]{16,})['\"]"
)

_Q = r"[\"']?\s*"
EDGE_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("realised or simulated ROI", re.compile(rf"(?i)\bROI\b{_Q}[:=]?\s*[+-]?\d")),
    ("win rate", re.compile(rf"(?i)\bwin[_ ]rate\b{_Q}[:=]?\s*[01]?\.\d+")),
    ("bankroll figure", re.compile(rf"(?i)\bbankroll\b{_Q}[:=]\s*\d")),
    ("edge threshold constant", re.compile(r"(?i)\b(WIN_SHARP|WIN_NAIVE|BACKTEST_PROJ)\w*\s*=")),
    ("kelly staking constant", re.compile(rf"(?i)\bkelly_fraction\b{_Q}[:=]\s*\d")),
    ("stake or entry sizing", re.compile(rf"(?i)\bmax_per_lineup\b{_Q}[:=]\s*\d")),
]

PLACEHOLDER = re.compile(
    r"(?i)(REPLACE_ME|CHANGEME|your[_-]?key|xxx+|<[^>]+>|example|dummy|placeholder|\.\.\.)"
)
TEXT_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".json", ".md", ".yml", ".yaml", ".toml",
                 ".cfg", ".ini", ".sh", ".ps1", ".sql", ".txt", ".example", ".env"}


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    return -sum((n := s.count(c) / len(s)) and n * math.log2(n) for c in set(s))


def _read(path: Path) -> str | None:
    if path.suffix.lower() not in TEXT_SUFFIXES and path.suffix:
        return None
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def scan_text(text: str, label: str, *, edges: bool = True) -> list[str]:
    findings: list[str] = []
    rules = SECRET_RULES + (EDGE_RULES if edges else [])
    for lineno, line in enumerate(text.splitlines(), start=1):
        if "leak-guard: allow" in line:
            continue
        for name, pat in rules:
            if pat.search(line):
                findings.append(f"{label}:{lineno}: {name}")
        m = ASSIGNED_SECRET.search(line)
        if m and not PLACEHOLDER.search(m.group(2)) and _entropy(m.group(2)) > 3.0:
            findings.append(f"{label}:{lineno}: assigned secret-like literal")
    return findings


def scan_paths(paths: Iterable[Path], *, edges: bool = True) -> list[str]:
    findings: list[str] = []
    for p in paths:
        text = _read(p)
        if text is None:
            continue
        rel = p.relative_to(ROOT) if p.is_absolute() and ROOT in p.parents else p
        findings.extend(scan_text(text, str(rel), edges=edges))
    return findings


def repo_files() -> list[Path]:
    import subprocess

    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout
    return [ROOT / ln.strip() for ln in out.splitlines() if ln.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--secrets-only", action="store_true",
                    help="skip edge rules (correct for the private repo)")
    ap.add_argument("paths", nargs="*", help="default: every tracked file")
    args = ap.parse_args()

    targets = [Path(p) for p in args.paths] if args.paths else repo_files()
    findings = scan_paths(targets, edges=not args.secrets_only)
    for f in findings:
        print(f"LEAK  {f}", file=sys.stderr)
    mode = "secrets" if args.secrets_only else "secrets+edges"
    print(f"scanned {len(targets)} files ({mode}); {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
