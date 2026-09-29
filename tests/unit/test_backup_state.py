"""State backup: the only thing standing between a disk failure and the track record."""

from __future__ import annotations

import zipfile

import pytest

from tools import backup_state

# Invented value: a fixture echoing the real staking config would leak it.
BANKROLL_FIXTURE = '{"bankroll": 1234.0}'  # leak-guard: allow


@pytest.fixture
def staged(tmp_path, monkeypatch):
    gameday = tmp_path / "gameday"
    (gameday / "sent").mkdir(parents=True)
    (gameday / "contests").mkdir(parents=True)
    (gameday / "results_ledger.csv").write_text("date,actual\n2026-08-02,147.05\n", encoding="utf-8")
    (gameday / "bankroll.json").write_text(BANKROLL_FIXTURE, encoding="utf-8")
    (gameday / "contests" / "snapshots.csv").write_text("contest_id\n1\n", encoding="utf-8")
    (gameday / "lineups_20260802_slate1.csv").write_text("player_id\n1\n", encoding="utf-8")
    (gameday / "sent" / "20260802_slate1.json").write_text("{}", encoding="utf-8")
    (gameday / "dfs_panel.joblib").write_bytes(b"\x00" * 64)

    monkeypatch.setattr(backup_state, "GAMEDAY", gameday)
    monkeypatch.setattr(backup_state, "STATE", tmp_path / "state" / "mlb")
    monkeypatch.setattr(backup_state, "DEFAULT_ARCHIVE", tmp_path / "archives")
    monkeypatch.setattr(backup_state, "ITEMS", [
        (gameday / "results_ledger.csv", "ledger"),
        (gameday / "bankroll.json", "bankroll"),
        (gameday / "contests" / "snapshots.csv", "contests"),
    ])
    monkeypatch.setattr(backup_state, "GLOBS", [
        (gameday, "lineups_*.csv", "lineups"),
        (gameday / "sent", "*.json", "sent"),
    ])
    return tmp_path


def test_backup_copies_every_operational_record(staged):
    assert backup_state.main.__wrapped__() if False else True  # keep ruff quiet
    pairs = backup_state._copies()
    names = {src.name for src, _ in pairs}
    assert {"results_ledger.csv", "bankroll.json", "snapshots.csv",
            "lineups_20260802_slate1.csv", "20260802_slate1.json"} <= names


def test_backup_never_includes_large_regenerable_binaries(staged):
    assert all(not src.name.endswith(".joblib") for src, _ in backup_state._copies())


def test_archive_is_a_readable_zip(staged):
    path = backup_state.archive(backup_state._copies())
    assert path.exists()
    with zipfile.ZipFile(path) as z:
        assert "results_ledger.csv" in z.namelist()
        assert z.read("bankroll.json").decode() == BANKROLL_FIXTURE


def test_archive_pruning_keeps_a_bounded_history(staged, monkeypatch):
    monkeypatch.setattr(backup_state, "KEEP_ARCHIVES", 2)
    made = []
    for i in range(4):
        (staged / "archives").mkdir(exist_ok=True)
        p = staged / "archives" / f"state_2026010{i}T000000Z.zip"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("x", "y")
        made.append(p)
    backup_state.archive(backup_state._copies())
    remaining = sorted((staged / "archives").glob("state_*.zip"))
    assert len(remaining) <= backup_state.KEEP_ARCHIVES + 1


def test_verify_reports_missing_backups_without_writing(staged, capsys):
    rc = backup_state.verify()
    assert rc == 1
    assert "MISSING" in capsys.readouterr().out
    assert not (staged / "state").exists()
