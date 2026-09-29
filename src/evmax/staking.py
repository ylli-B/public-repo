"""Turning an edge into a stake, independent of what produced the edge.

Kelly sizing is the same maths whether the wager is a DFS double up, a sports
bet, or any other binary payout, so it lives in the platform rather than in a
sport. Domain modules supply the win probability and the payout; this decides
how much of the bankroll to risk.

Kelly for a binary payout: f* = (b*p - q) / b, where b is net odds. Full Kelly
maximises long-run growth but is far too volatile in practice, so callers pass a
fraction — a quarter is the usual choice.
"""

from __future__ import annotations

from dataclasses import dataclass


def kelly(p: float, b: float) -> float:
    """Optimal fraction of bankroll for a binary bet, floored at zero.

    p: probability of winning. b: net odds (1.8x payout -> b = 0.8).
    Returns 0 when there is no edge, so a losing proposition never sizes up.
    """
    if b <= 0:
        return 0.0
    return max((b * p - (1 - p)) / b, 0.0)


def breakeven(b: float) -> float:
    """Win rate at which a bet is exactly EV-neutral."""
    return 1.0 / (1.0 + b) if b > 0 else 1.0


@dataclass(frozen=True)
class Stake:
    per_entry: float
    entries: int
    total: float
    skip: bool
    reason: str | None = None


def size(bankroll: float, p: float, b: float, *, fraction: float = 0.25,
         entries: int = 1, cap: float | None = None, minimum: float = 0.0,
         whole_units: bool = True) -> Stake:
    """Fractional-Kelly stake for `entries` correlated tickets.

    Correlated entries share one outcome, so the Kelly budget is computed once
    for the slate and then divided, never multiplied. `cap` is a hard per-entry
    ceiling that always wins over the Kelly result.
    """
    entries = max(int(entries), 1)
    if bankroll <= 0 or bankroll < minimum:
        return Stake(0.0, entries, 0.0, True, "bankroll below minimum entry")

    budget = bankroll * kelly(p, b) * fraction
    per = budget / entries
    if cap is not None:
        per = min(per, cap)
    if whole_units:
        per = float(int(per))

    if per < minimum:
        if bankroll >= minimum and kelly(p, b) > 0:
            return Stake(minimum, 1, minimum, False, "kelly below the contest minimum")
        return Stake(0.0, entries, 0.0, True, "no edge or bankroll too small")

    total = per * entries
    if total > bankroll:
        entries = max(int(bankroll // max(per, 1e-9)), 0)
        total = per * entries
        if entries == 0:
            return Stake(0.0, 0, 0.0, True, "bankroll cannot cover one entry")
    return Stake(per, entries, total, False, None)
