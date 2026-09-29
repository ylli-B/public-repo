"""Back up operational state so a dead disk cannot erase the track record.

Two destinations, deliberately:

  state/      small, human-readable operational records committed to the private
              repo. The ledger and bankroll are business records, not model
              secrets, and putting them in git gives offsite durability, history
              and diffability for free.
  archive     a timestamped zip outside the repo, so a bad `git clean` or a
              rewritten history is not a single point of failure.

Large binaries (trained panels, joblib caches) are deliberately NOT backed up:
they are regenerable from bronze and would bloat the repo.

Usage:
    python -m tools.backup_state                 # copy into state/ and archive
    python -m tools.backup_state --verify        # report freshness, change nothing
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAMEDAY = ROOT / "ml" / "artifacts" / "mlb" / "gameday"
STATE = ROOT / "state" / "mlb"
DEFAULT_ARCHIVE = Path(os.getenv("EVMAX_BACKUP_DIR",
                                 Path.home() / "EVMaxBackups"))
KEEP_ARCHIVES = 30

# (source, description). Small text records only.
ITEMS: list[tuple[Path, str]] = [
    (GAMEDAY / "results_ledger.csv", "graded lineup results"),
    (GAMEDAY / "results_summary.json", "results rollup"),
    (GAMEDAY / "bankroll.json", "bankroll and staking config"),
    (GAMEDAY / "contests" / "snapshots.csv", "contest fill snapshots"),
]
GLOBS: list[tuple[Path, str, str]] = [
    (GAMEDAY, "lineups_*.csv", "built lineups"),
    (GAMEDAY / "sent", "*.json", "alert send state"),
]


def _copies() -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    for src, _ in ITEMS:
        if src.exists():
            pairs.append((src, STATE / src.relative_to(GAMEDAY)))
    for base, pattern, _ in GLOBS:
        if not base.exists():
            continue
        for src in sorted(base.glob(pattern)):
            pairs.append((src, STATE / src.relative_to(GAMEDAY)))
    return pairs


def copy_records() -> list[tuple[Path, Path]]:
    """Copy every operational record into `state/`. Returns the pairs copied."""
    pairs = _copies()
    for src, dst in pairs:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    if pairs:
        STATE.mkdir(parents=True, exist_ok=True)
        (STATE / "MANIFEST.json").write_text(json.dumps({
            "backed_up_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "files": [str(dst.relative_to(STATE)).replace("\\", "/") for _, dst in pairs],
        }, indent=2), encoding="utf-8")
    return pairs


def verify() -> int:
    """Report what exists and how stale the backup is. Never writes."""
    now = datetime.now(UTC)
    missing = 0
    print(f"{'record':<34}{'source':>10}{'backup':>10}  age")
    for src, dst in _copies():
        s_age = (now.timestamp() - src.stat().st_mtime) / 3600
        has_dst = dst.exists()
        d_age = ((now.timestamp() - dst.stat().st_mtime) / 3600) if has_dst else None
        missing += 0 if has_dst else 1
        age = f"{d_age:.1f}h" if d_age is not None else "MISSING"
        print(f"{src.name[:34]:<34}{s_age:>9.1f}h{'yes' if has_dst else 'no':>10}  {age}")
    archives = sorted(DEFAULT_ARCHIVE.glob("state_*.zip")) if DEFAULT_ARCHIVE.exists() else []
    print(f"\narchives in {DEFAULT_ARCHIVE}: {len(archives)}")
    if archives:
        print(f"  newest: {archives[-1].name}")
    if missing:
        print(f"\n{missing} record(s) not yet backed up — run without --verify")
    return 1 if missing else 0


def archive(pairs: list[tuple[Path, Path]]) -> Path:
    DEFAULT_ARCHIVE.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = DEFAULT_ARCHIVE / f"state_{stamp}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for src, _ in pairs:
            z.write(src, src.relative_to(GAMEDAY).as_posix())
    old = sorted(DEFAULT_ARCHIVE.glob("state_*.zip"))[:-KEEP_ARCHIVES]
    for p in old:
        p.unlink()
    if old:
        print(f"pruned {len(old)} old archive(s)")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verify", action="store_true", help="report only")
    ap.add_argument("--no-archive", action="store_true", help="skip the zip")
    args = ap.parse_args()

    if args.verify:
        return verify()

    pairs = copy_records()
    if not pairs:
        print("no operational state to back up yet")
        return 0
    print(f"copied {len(pairs)} record(s) into {STATE}")

    if not args.no_archive:
        print(f"archived to {archive(pairs)}")
    print("\ncommit state/ to keep the offsite copy current:")
    print("  git add state && git commit -m \"state: back up operational records\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
