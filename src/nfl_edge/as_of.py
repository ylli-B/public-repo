"""Point-in-time (as_of_ts) helpers — mandatory for features and joins."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

import pandas as pd

NEAR_KICKOFF_OFFSETS = (
    timedelta(hours=24),
    timedelta(hours=6),
    timedelta(minutes=90),
    timedelta(minutes=15),
)


def ensure_utc(ts: datetime | pd.Timestamp) -> datetime:
    """Normalize a timestamp to timezone-aware UTC."""
    if isinstance(ts, pd.Timestamp):
        ts = ts.to_pydatetime()
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def as_of_label(offset: timedelta) -> str:
    total_min = int(offset.total_seconds() // 60)
    if total_min >= 60 and total_min % 60 == 0:
        return f"T-{total_min // 60}h"
    return f"T-{total_min}m"


def kickoff_as_of_ts(kickoff_ts: datetime | pd.Timestamp, offset: timedelta) -> datetime:
    """Feature cutoff timestamp for a given near-kickoff cadence."""
    return ensure_utc(kickoff_ts) - offset


def all_kickoff_as_of(kickoff_ts: datetime | pd.Timestamp) -> dict[str, datetime]:
    return {as_of_label(o): kickoff_as_of_ts(kickoff_ts, o) for o in NEAR_KICKOFF_OFFSETS}


def filter_as_of(
    df: pd.DataFrame,
    as_of_ts: datetime | pd.Timestamp,
    *,
    event_col: str = "event_ts",
    as_of_col: str | None = "as_of_ts",
) -> pd.DataFrame:
    """
    Keep only rows that would have been known at as_of_ts.

    If as_of_col is present, require as_of_col <= as_of_ts.
    Always require event_col <= as_of_ts when present.
    """
    cutoff = ensure_utc(as_of_ts)
    out = df.copy()
    if event_col in out.columns:
        out = out[pd.to_datetime(out[event_col], utc=True) <= cutoff]
    if as_of_col and as_of_col in out.columns:
        out = out[pd.to_datetime(out[as_of_col], utc=True) <= cutoff]
    return out.reset_index(drop=True)


def assert_no_future_leakage(
    features: pd.DataFrame,
    *,
    as_of_col: str = "as_of_ts",
    event_cols: Iterable[str] = ("event_ts", "published_ts", "snapshot_ts"),
) -> None:
    """Raise if any event timestamp is after the row's as_of_ts."""
    if as_of_col not in features.columns:
        raise ValueError(f"Missing required column: {as_of_col}")

    as_of = pd.to_datetime(features[as_of_col], utc=True)
    for col in event_cols:
        if col not in features.columns:
            continue
        events = pd.to_datetime(features[col], utc=True)
        leaked = events > as_of
        if leaked.any():
            n = int(leaked.sum())
            raise AssertionError(f"Leakage: {n} rows have {col} > {as_of_col}")


def attach_as_of_ts(
    df: pd.DataFrame,
    as_of_ts: datetime | pd.Timestamp,
    *,
    col: str = "as_of_ts",
) -> pd.DataFrame:
    out = df.copy()
    out[col] = ensure_utc(as_of_ts)
    return out
