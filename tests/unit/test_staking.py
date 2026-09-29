"""Platform staking maths, independent of any sport or market."""

from __future__ import annotations

import pytest

from evmax.staking import breakeven, kelly, size


def test_kelly_is_zero_without_an_edge():
    b = 0.8
    assert kelly(breakeven(b), b) == pytest.approx(0.0, abs=1e-12)
    assert kelly(0.4, b) == 0.0


def test_kelly_rises_with_probability():
    b = 1.0
    assert kelly(0.7, b) > kelly(0.6, b) > kelly(0.55, b) > 0


def test_breakeven_matches_the_payout():
    assert breakeven(1.0) == pytest.approx(0.5)
    assert breakeven(0.8) == pytest.approx(1 / 1.8)


def test_zero_or_negative_odds_never_size():
    assert kelly(0.9, 0.0) == 0.0
    assert kelly(0.9, -1.0) == 0.0


def test_correlated_entries_divide_the_budget_rather_than_multiply_it():
    one = size(1000.0, 0.60, 0.8, entries=1, cap=None, whole_units=False)
    four = size(1000.0, 0.60, 0.8, entries=4, cap=None, whole_units=False)
    assert four.total == pytest.approx(one.total)
    assert four.per_entry == pytest.approx(one.per_entry / 4)


def test_cap_always_beats_kelly():
    s = size(1_000_000.0, 0.60, 0.8, cap=25.0)
    assert s.per_entry == 25.0


def test_never_stakes_more_than_the_bankroll():
    for bankroll in (1.0, 7.0, 25.0, 400.0):
        s = size(bankroll, 0.60, 0.8, entries=3, cap=50.0, minimum=5.0)
        assert s.total <= bankroll


def test_bankroll_below_the_minimum_entry_skips():
    s = size(2.0, 0.60, 0.8, minimum=5.0)
    assert s.skip and s.total == 0.0


def test_no_edge_skips_even_with_a_big_bankroll():
    s = size(10_000.0, 0.40, 0.8, minimum=5.0)
    assert s.skip


def test_whole_units_produce_clean_stakes():
    s = size(377.0, 0.60, 0.8, cap=100.0)
    assert float(s.per_entry).is_integer()
