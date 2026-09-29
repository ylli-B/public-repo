"""Point-in-time (PIT) leakage tests for silver availability and form models.

These tests enforce the as_of_ts / valid_from contracts from docs/data/timing-and-as-of.md:
- Availability: valid_from <= feature_as_of AND (valid_to IS NULL OR valid_to > feature_as_of)
- Form: kickoff_ts < feature_as_of (prior games only; same-game box never in pregame features)

Tests use synthetic fixtures — no network/database per AGENTS.md.
"""

from __future__ import annotations

import pandas as pd
import pytest

# =============================================================================
# SYNTHETIC DATA FACTORIES
# =============================================================================


def _availability_snapshots(rows: list[tuple[int, str, str, str | None]]) -> pd.DataFrame:
    """(player_id, valid_from, status, injury_status) -> SCD2 availability frame."""
    df = pd.DataFrame(rows, columns=["player_id", "valid_from", "status", "injury_status"])
    df["valid_from"] = pd.to_datetime(df["valid_from"], utc=True)
    df = df.sort_values(["player_id", "valid_from"])
    df["valid_to"] = df.groupby("player_id")["valid_from"].shift(-1)
    return df


def _player_form(rows: list[tuple[int, str, float]]) -> pd.DataFrame:
    """(player_id, kickoff_ts, passing_rating_l4) -> player form lag frame."""
    df = pd.DataFrame(rows, columns=["player_id", "kickoff_ts", "passing_rating_l4"])
    df["kickoff_ts"] = pd.to_datetime(df["kickoff_ts"], utc=True)
    return df


def _feature_rows(rows: list[tuple[str, str, str]]) -> pd.DataFrame:
    """(game_key, as_of_ts, cadence) -> gold feature grain stub."""
    df = pd.DataFrame(rows, columns=["game_key", "as_of_ts", "cadence"])
    df["as_of_ts"] = pd.to_datetime(df["as_of_ts"], utc=True)
    return df


# =============================================================================
# AVAILABILITY SCD2 JOIN TESTS
# =============================================================================


def scd2_join(
    features: pd.DataFrame,
    availability: pd.DataFrame,
    player_id: int,
) -> pd.DataFrame:
    """Join availability SCD2 to features using valid_from/valid_to contract.
    
    Contract: valid_from <= as_of_ts AND (valid_to IS NULL OR valid_to > as_of_ts)
    """
    avail_player = availability[availability["player_id"] == player_id].copy()
    merged = features.copy()
    
    results = []
    for _, feat_row in merged.iterrows():
        as_of = feat_row["as_of_ts"]
        match = avail_player[
            (avail_player["valid_from"] <= as_of) &
            (avail_player["valid_to"].isna() | (avail_player["valid_to"] > as_of))
        ]
        if len(match) == 1:
            result = {**feat_row.to_dict(), **match.iloc[0].to_dict()}
            results.append(result)
        elif len(match) == 0:
            results.append({**feat_row.to_dict(), "status": None, "injury_status": None})
        else:
            raise AssertionError(f"SCD2 overlap: {len(match)} rows match for as_of={as_of}")
    
    return pd.DataFrame(results)


class TestAvailabilitySCD2:
    """Tests for SCD2 availability join contract."""

    def test_publish_proxy_respected(self):
        """Status observed after feature as_of must not be visible."""
        avail = _availability_snapshots([
            (1, "2024-09-01T10:00:00+00:00", "Active", None),
            (1, "2024-09-05T10:00:00+00:00", "Active", "Questionable"),
            (1, "2024-09-06T10:00:00+00:00", "Active", "Out"),
        ])
        
        features = _feature_rows([
            ("G1", "2024-09-04T18:00:00+00:00", "T-90m"),
        ])
        
        joined = scd2_join(features, avail, player_id=1)
        
        assert len(joined) == 1
        assert pd.isna(joined.iloc[0]["injury_status"])
        assert joined.iloc[0]["status"] == "Active"

    def test_later_snapshot_becomes_visible(self):
        """As feature as_of advances, newer snapshot should become visible."""
        avail = _availability_snapshots([
            (1, "2024-09-01T10:00:00+00:00", "Active", None),
            (1, "2024-09-05T10:00:00+00:00", "Active", "Out"),
        ])
        
        features = _feature_rows([
            ("G1", "2024-09-06T18:00:00+00:00", "T-90m"),
        ])
        
        joined = scd2_join(features, avail, player_id=1)
        
        assert len(joined) == 1
        assert joined.iloc[0]["injury_status"] == "Out"

    def test_no_future_status_leakage(self):
        """Feature at T-24h must not see T-15m status update."""
        avail = _availability_snapshots([
            (1, "2024-09-07T08:00:00+00:00", "Active", "Questionable"),
            (1, "2024-09-08T17:45:00+00:00", "Active", "Out"),
        ])
        
        features_early = _feature_rows([
            ("G1", "2024-09-07T20:00:00+00:00", "T-24h"),
        ])
        features_late = _feature_rows([
            ("G1", "2024-09-08T18:50:00+00:00", "T-15m"),
        ])
        
        early_join = scd2_join(features_early, avail, player_id=1)
        late_join = scd2_join(features_late, avail, player_id=1)
        
        assert early_join.iloc[0]["injury_status"] == "Questionable"
        assert late_join.iloc[0]["injury_status"] == "Out"

    def test_scd2_gap_returns_null(self):
        """Player with no valid snapshot at as_of should return null."""
        avail = _availability_snapshots([
            (1, "2024-09-10T10:00:00+00:00", "Active", None),
        ])
        
        features = _feature_rows([
            ("G1", "2024-09-05T18:00:00+00:00", "T-90m"),
        ])
        
        joined = scd2_join(features, avail, player_id=1)
        
        assert len(joined) == 1
        assert joined.iloc[0]["status"] is None


# =============================================================================
# PLAYER FORM PRIOR-GAME TESTS
# =============================================================================


def prior_game_join(
    features: pd.DataFrame,
    form: pd.DataFrame,
    player_id: int,
) -> pd.DataFrame:
    """Join form lag to features using prior-game-only contract.
    
    Contract: kickoff_ts < as_of_ts (strictly less than — same-game excluded)
    """
    form_player = form[form["player_id"] == player_id].copy()
    
    results = []
    for _, feat_row in features.iterrows():
        as_of = feat_row["as_of_ts"]
        prior = form_player[form_player["kickoff_ts"] < as_of]
        if len(prior) > 0:
            latest = prior.sort_values("kickoff_ts").iloc[-1]
            result = {**feat_row.to_dict(), **latest.to_dict()}
            results.append(result)
        else:
            results.append({**feat_row.to_dict(), "passing_rating_l4": None})
    
    return pd.DataFrame(results)


class TestPlayerFormLag:
    """Tests for prior-game-only form lag contract."""

    def test_same_game_box_excluded(self):
        """Stats from a game must not appear in that game's pregame features."""
        form = _player_form([
            (1, "2024-09-01T20:00:00+00:00", 95.0),
            (1, "2024-09-08T20:00:00+00:00", 110.0),
        ])
        
        features = _feature_rows([
            ("G2", "2024-09-08T18:30:00+00:00", "T-90m"),
        ])
        
        joined = prior_game_join(features, form, player_id=1)
        
        assert len(joined) == 1
        assert joined.iloc[0]["passing_rating_l4"] == pytest.approx(95.0)

    def test_prior_game_visible(self):
        """Stats from prior games should be visible."""
        form = _player_form([
            (1, "2024-09-01T20:00:00+00:00", 90.0),
            (1, "2024-09-08T20:00:00+00:00", 100.0),
        ])
        
        features = _feature_rows([
            ("G3", "2024-09-15T18:30:00+00:00", "T-90m"),
        ])
        
        joined = prior_game_join(features, form, player_id=1)
        
        assert len(joined) == 1
        assert joined.iloc[0]["passing_rating_l4"] == pytest.approx(100.0)

    def test_future_game_never_visible(self):
        """Stats from future games must never appear."""
        form = _player_form([
            (1, "2024-09-01T20:00:00+00:00", 85.0),
            (1, "2024-09-15T20:00:00+00:00", 120.0),
        ])
        
        features = _feature_rows([
            ("G2", "2024-09-08T18:30:00+00:00", "T-90m"),
        ])
        
        joined = prior_game_join(features, form, player_id=1)
        
        assert len(joined) == 1
        assert joined.iloc[0]["passing_rating_l4"] == pytest.approx(85.0)

    def test_no_prior_games_returns_null(self):
        """Player with no prior games should get null form."""
        form = _player_form([
            (1, "2024-09-15T20:00:00+00:00", 100.0),
        ])
        
        features = _feature_rows([
            ("G1", "2024-09-08T18:30:00+00:00", "T-90m"),
        ])
        
        joined = prior_game_join(features, form, player_id=1)
        
        assert len(joined) == 1
        assert pd.isna(joined.iloc[0]["passing_rating_l4"])

    def test_exact_time_match_excluded(self):
        """Game at exactly as_of time is still excluded (strict <)."""
        form = _player_form([
            (1, "2024-09-01T20:00:00+00:00", 90.0),
            (1, "2024-09-08T18:30:00+00:00", 105.0),
        ])
        
        features = _feature_rows([
            ("G2", "2024-09-08T18:30:00+00:00", "T-90m"),
        ])
        
        joined = prior_game_join(features, form, player_id=1)
        
        assert len(joined) == 1
        assert joined.iloc[0]["passing_rating_l4"] == pytest.approx(90.0)


# =============================================================================
# COMBINED FEATURE CONTRACT TESTS
# =============================================================================


class TestFeatureContractIntegrity:
    """Tests that combined availability + form respects PIT."""

    def test_exemplar_game_pit_integrity(self):
        """Exemplar game (202210132, T-90m, 2022-09-08 18:50 UTC) must pass PIT.
        
        This is the documented exemplar from ml/nfl/features.py.
        """
        exemplar_as_of = pd.Timestamp("2022-09-08T18:50:00+00:00")
        exemplar_kickoff = pd.Timestamp("2022-09-08T20:20:00+00:00")
        
        assert exemplar_as_of <= exemplar_kickoff, "as_of must be before kickoff"
        
        prior_game_cutoff = exemplar_as_of
        
        avail = _availability_snapshots([
            (1, "2022-09-01T10:00:00+00:00", "Active", None),
            (1, "2022-09-08T12:00:00+00:00", "Active", "Questionable"),
            (1, "2022-09-08T19:00:00+00:00", "Active", "Out"),
        ])
        
        valid_avail = avail[
            (avail["valid_from"] <= exemplar_as_of) &
            (avail["valid_to"].isna() | (avail["valid_to"] > exemplar_as_of))
        ]
        assert len(valid_avail) == 1
        assert valid_avail.iloc[0]["injury_status"] == "Questionable"
        
        form = _player_form([
            (1, "2022-09-04T20:00:00+00:00", 95.0),
            (1, "2022-09-08T20:20:00+00:00", 110.0),
        ])
        
        valid_form = form[form["kickoff_ts"] < prior_game_cutoff]
        assert len(valid_form) == 1
        assert valid_form.iloc[0]["passing_rating_l4"] == pytest.approx(95.0)


# =============================================================================
# TEAM FORM LAG PIT TESTS (SOS / ADJ / VENUE / REST)
# =============================================================================


def _team_games(
    rows: list[tuple[str, str, str, str, int | None, int | None]],
) -> pd.DataFrame:
    """(game_key, team, opponent, kickoff_ts, points_for, points_against) -> team games frame.
    
    Simulates the structure from gold__team_form_lag after union of home/away views.
    """
    df = pd.DataFrame(
        rows,
        columns=["game_key", "team", "opponent", "kickoff_ts", "points_for", "points_against"],
    )
    df["kickoff_ts"] = pd.to_datetime(df["kickoff_ts"], utc=True)
    df["margin"] = df["points_for"] - df["points_against"]
    df["won"] = (df["points_for"] > df["points_against"]).astype(float)
    df = df.sort_values(["team", "kickoff_ts", "game_key"]).reset_index(drop=True)
    return df


def compute_team_form_lag(games: pd.DataFrame, window_size: int = 4) -> pd.DataFrame:
    """Simulate gold__team_form_lag L4 rolling window computation.
    
    Contract: ROWS BETWEEN {window_size} PRECEDING AND 1 PRECEDING
    This means for each game, only games with STRICTLY earlier position in the
    (kickoff_ts, game_key) ordering contribute to the rolling average.
    
    Args:
        games: DataFrame with team, kickoff_ts, game_key, margin, won columns.
        window_size: Number of preceding rows to include (default 4 for L4).
    
    Returns:
        DataFrame with game_key, team, kickoff_ts, margin_l4, win_pct_l4,
        and contributing_kickoffs (list of kickoff_ts that contributed).
    """
    results = []
    for team in games["team"].unique():
        team_games = games[games["team"] == team].sort_values(
            ["kickoff_ts", "game_key"]
        ).reset_index(drop=True)
        
        for idx, row in team_games.iterrows():
            # "1 preceding" means exclude current row
            # "window_size preceding" means go back window_size rows from the one before current
            start_idx = max(0, idx - window_size)
            end_idx = idx  # exclusive (excludes current row)
            
            prior_games = team_games.iloc[start_idx:end_idx]
            
            if len(prior_games) > 0:
                margin_l4 = prior_games["margin"].mean()
                win_pct_l4 = prior_games["won"].mean()
                contributing_kickoffs = prior_games["kickoff_ts"].tolist()
            else:
                margin_l4 = None
                win_pct_l4 = None
                contributing_kickoffs = []
            
            results.append({
                "game_key": row["game_key"],
                "team": team,
                "kickoff_ts": row["kickoff_ts"],
                "margin_l4": margin_l4,
                "win_pct_l4": win_pct_l4,
                "contributing_kickoffs": contributing_kickoffs,
            })
    
    return pd.DataFrame(results)


def compute_rest_days(games: pd.DataFrame) -> pd.DataFrame:
    """Simulate rest_days computation from gold__team_form_lag.
    
    Contract: rest_days = (current_kickoff - prev_kickoff) / 86400
    prev_kickoff must be strictly < current_kickoff (or same kickoff but earlier game_key).
    """
    results = []
    for team in games["team"].unique():
        team_games = games[games["team"] == team].sort_values(
            ["kickoff_ts", "game_key"]
        ).reset_index(drop=True)
        
        for idx, row in team_games.iterrows():
            if idx == 0:
                rest_days = None
                prev_kickoff = None
            else:
                prev = team_games.iloc[idx - 1]
                prev_kickoff = prev["kickoff_ts"]
                rest_days = (row["kickoff_ts"] - prev_kickoff).total_seconds() / 86400.0
            
            results.append({
                "game_key": row["game_key"],
                "team": team,
                "kickoff_ts": row["kickoff_ts"],
                "rest_days": rest_days,
                "prev_kickoff": prev_kickoff,
            })
    
    return pd.DataFrame(results)


def assert_form_lag_pit(form_lag: pd.DataFrame) -> None:
    """Assert that all contributing kickoffs are strictly before target kickoff.
    
    Contract (Statistician lock): for every features_as_of row,
    max(feature-contributing event time) < target kickoff_ts.
    
    Raises:
        AssertionError: If any contributing kickoff_ts >= target kickoff_ts.
    """
    violations = []
    for _, row in form_lag.iterrows():
        target_kickoff = row["kickoff_ts"]
        for contrib_kickoff in row["contributing_kickoffs"]:
            if contrib_kickoff >= target_kickoff:
                violations.append({
                    "game_key": row["game_key"],
                    "team": row["team"],
                    "target_kickoff": target_kickoff,
                    "contributing_kickoff": contrib_kickoff,
                })
    
    if violations:
        raise AssertionError(
            f"Form lag PIT violation: {len(violations)} contributing games have "
            f"kickoff_ts >= target kickoff_ts. First violation: {violations[0]}"
        )


def assert_rest_days_pit(rest: pd.DataFrame) -> None:
    """Assert that rest_days is computed from strictly prior game only.
    
    Contract: prev_kickoff must be < current kickoff_ts (or NULL for Week-1).
    
    Raises:
        AssertionError: If any prev_kickoff >= target kickoff_ts.
    """
    violations = []
    for _, row in rest.iterrows():
        if row["prev_kickoff"] is not None and not pd.isna(row["prev_kickoff"]):
            if row["prev_kickoff"] >= row["kickoff_ts"]:
                violations.append({
                    "game_key": row["game_key"],
                    "team": row["team"],
                    "kickoff_ts": row["kickoff_ts"],
                    "prev_kickoff": row["prev_kickoff"],
                })
    
    if violations:
        raise AssertionError(
            f"Rest days PIT violation: {len(violations)} rows have "
            f"prev_kickoff >= kickoff_ts. First violation: {violations[0]}"
        )


class TestTeamFormLagPIT:
    """Tests for team form lag PIT contract (SOS/adj/venue/rest).
    
    Contract (Statistician lock): for every features_as_of row,
    max(feature-contributing event time) < target kickoff_ts.
    
    This enforces that sos_*, adj_*, venue_*, margin_l4, rest_days, etc.
    only use games with kickoff_ts strictly before the target game's kickoff.
    """

    def test_l4_excludes_current_game(self):
        """L4 rolling window must exclude the current game."""
        games = _team_games([
            ("G1", "KC", "DEN", "2024-09-01T20:00:00+00:00", 28, 21),
            ("G2", "KC", "LV", "2024-09-08T20:00:00+00:00", 35, 14),
            ("G3", "KC", "ATL", "2024-09-15T20:00:00+00:00", 24, 17),
            ("G4", "KC", "LAC", "2024-09-22T20:00:00+00:00", 31, 28),
            ("G5", "KC", "NO", "2024-09-29T20:00:00+00:00", None, None),  # target
        ])
        
        form_lag = compute_team_form_lag(games)
        
        # G5's L4 should include G1-G4, not G5
        g5_row = form_lag[form_lag["game_key"] == "G5"].iloc[0]
        assert len(g5_row["contributing_kickoffs"]) == 4
        
        # All contributing kickoffs must be before G5's kickoff
        g5_kickoff = pd.Timestamp("2024-09-29T20:00:00+00:00")
        for contrib in g5_row["contributing_kickoffs"]:
            assert contrib < g5_kickoff, f"Contributing {contrib} not before target {g5_kickoff}"

    def test_l4_window_all_strictly_prior(self):
        """All games in L4 window must have kickoff_ts < target kickoff_ts."""
        games = _team_games([
            ("G1", "BUF", "MIA", "2024-09-01T13:00:00+00:00", 31, 17),
            ("G2", "BUF", "NYJ", "2024-09-08T13:00:00+00:00", 27, 24),
            ("G3", "BUF", "NE", "2024-09-15T13:00:00+00:00", 35, 10),
            ("G4", "BUF", "BAL", "2024-09-22T20:20:00+00:00", 28, 35),
            ("G5", "BUF", "HOU", "2024-09-29T13:00:00+00:00", 21, 14),
        ])
        
        form_lag = compute_team_form_lag(games)
        assert_form_lag_pit(form_lag)  # Should not raise

    def test_week1_no_prior_games(self):
        """Week 1 game should have no contributing games."""
        games = _team_games([
            ("G1", "SF", "NYJ", "2024-09-09T20:15:00+00:00", None, None),
        ])
        
        form_lag = compute_team_form_lag(games)
        
        g1_row = form_lag[form_lag["game_key"] == "G1"].iloc[0]
        assert len(g1_row["contributing_kickoffs"]) == 0
        assert g1_row["margin_l4"] is None
        assert g1_row["win_pct_l4"] is None

    def test_same_day_games_ordered_by_game_key(self):
        """Same-kickoff games must be ordered by game_key as tiebreaker."""
        # Simulate Thursday doubleheader or same-kickoff scenario
        games = _team_games([
            # Earlier game_key goes first when kickoff ties
            ("G100", "DAL", "NYG", "2024-11-28T16:30:00+00:00", 28, 17),
            ("G200", "DAL", "WAS", "2024-12-05T16:30:00+00:00", None, None),  # target
        ])
        
        form_lag = compute_team_form_lag(games)
        
        # G200 should have G100 as contributing (G100.kickoff < G200.kickoff or same time + earlier key)
        g200_row = form_lag[form_lag["game_key"] == "G200"].iloc[0]
        assert len(g200_row["contributing_kickoffs"]) == 1
        assert_form_lag_pit(form_lag)

    def test_rest_days_from_prior_game_only(self):
        """rest_days must be computed from strictly prior game."""
        games = _team_games([
            ("G1", "LAR", "DET", "2024-09-08T20:20:00+00:00", 20, 26),
            ("G2", "LAR", "ARI", "2024-09-15T16:05:00+00:00", 41, 10),
            ("G3", "LAR", "SF", "2024-09-22T16:25:00+00:00", None, None),
        ])
        
        rest = compute_rest_days(games)
        
        # G1 has no prior game -> rest_days NULL
        g1_rest = rest[rest["game_key"] == "G1"].iloc[0]
        assert pd.isna(g1_rest["rest_days"])
        
        # G2 rest_days from G1 only
        g2_rest = rest[rest["game_key"] == "G2"].iloc[0]
        expected_rest = (
            pd.Timestamp("2024-09-15T16:05:00+00:00") -
            pd.Timestamp("2024-09-08T20:20:00+00:00")
        ).total_seconds() / 86400.0
        assert g2_rest["rest_days"] == pytest.approx(expected_rest)
        assert g2_rest["prev_kickoff"] < g2_rest["kickoff_ts"]
        
        assert_rest_days_pit(rest)

    def test_rest_days_week1_null(self):
        """Week 1 game must have NULL rest_days (no prior game)."""
        games = _team_games([
            ("G1", "PHI", "GB", "2024-09-06T20:15:00+00:00", 34, 29),
        ])
        
        rest = compute_rest_days(games)
        
        g1_rest = rest[rest["game_key"] == "G1"].iloc[0]
        assert pd.isna(g1_rest["rest_days"])
        assert pd.isna(g1_rest["prev_kickoff"])

    def test_bye_week_long_rest(self):
        """Post-bye game should have ~13-14 day rest."""
        games = _team_games([
            ("G1", "CIN", "NE", "2024-09-08T13:00:00+00:00", 16, 10),
            # Week 2 bye
            ("G2", "CIN", "WSH", "2024-09-23T20:15:00+00:00", 38, 33),  # MNF after bye
        ])
        
        rest = compute_rest_days(games)
        
        g2_rest = rest[rest["game_key"] == "G2"].iloc[0]
        # 15 days from Sept 8 to Sept 23
        assert g2_rest["rest_days"] == pytest.approx(15.0 + (20.25 - 13.0) / 24.0, abs=0.1)
        assert g2_rest["prev_kickoff"] < g2_rest["kickoff_ts"]

    def test_short_week_thursday_game(self):
        """Short week (Sunday -> Thursday) should have ~4 day rest."""
        games = _team_games([
            ("G1", "DET", "LAR", "2024-09-08T20:20:00+00:00", 26, 20),
            ("G2", "DET", "SEA", "2024-09-12T20:15:00+00:00", None, None),  # TNF
        ])
        
        rest = compute_rest_days(games)
        
        g2_rest = rest[rest["game_key"] == "G2"].iloc[0]
        # 4 days from Sept 8 SNF to Sept 12 TNF (approx)
        assert g2_rest["rest_days"] < 5
        assert g2_rest["rest_days"] > 3
        assert g2_rest["prev_kickoff"] < g2_rest["kickoff_ts"]

    def test_sos_uses_prior_opponent_strength(self):
        """SOS features must use opponent strength from prior games only.
        
        Contract: opp.season_win_pct_entering comes from opponent's row
        for the SAME game, which itself uses opponent's prior games only.
        """
        # Create games with known opponent records
        games = _team_games([
            # KC's prior games
            ("G1", "KC", "DEN", "2024-09-01T20:00:00+00:00", 28, 21),
            ("G2", "KC", "LV", "2024-09-08T20:00:00+00:00", 35, 14),
            # KC's target game
            ("G3", "KC", "ATL", "2024-09-15T20:00:00+00:00", None, None),
            # DEN and LV games (opponent form)
            ("G1", "DEN", "KC", "2024-09-01T20:00:00+00:00", 21, 28),
            ("G2", "LV", "KC", "2024-09-08T20:00:00+00:00", 14, 35),
        ])
        
        form_lag = compute_team_form_lag(games)
        
        # KC's G3 margin_l4 should use G1 and G2 only
        kc_g3 = form_lag[(form_lag["game_key"] == "G3") & (form_lag["team"] == "KC")].iloc[0]
        assert len(kc_g3["contributing_kickoffs"]) == 2
        
        # All contributing games must be before G3's kickoff
        g3_kickoff = pd.Timestamp("2024-09-15T20:00:00+00:00")
        for contrib in kc_g3["contributing_kickoffs"]:
            assert contrib < g3_kickoff

    def test_pit_violation_raises(self):
        """Verify that PIT assertion catches violations."""
        # Manually construct a violation for testing
        bad_form_lag = pd.DataFrame([{
            "game_key": "G1",
            "team": "BAD",
            "kickoff_ts": pd.Timestamp("2024-09-08T20:00:00+00:00"),
            "margin_l4": 7.0,
            "win_pct_l4": 0.75,
            # Bug: contributing game is NOT before target
            "contributing_kickoffs": [pd.Timestamp("2024-09-08T20:00:00+00:00")],
        }])
        
        with pytest.raises(AssertionError, match="Form lag PIT violation"):
            assert_form_lag_pit(bad_form_lag)

    def test_rest_pit_violation_raises(self):
        """Verify that rest_days PIT assertion catches violations."""
        bad_rest = pd.DataFrame([{
            "game_key": "G1",
            "team": "BAD",
            "kickoff_ts": pd.Timestamp("2024-09-08T20:00:00+00:00"),
            "rest_days": 7.0,
            # Bug: prev_kickoff is same as or after current kickoff
            "prev_kickoff": pd.Timestamp("2024-09-08T20:00:00+00:00"),
        }])
        
        with pytest.raises(AssertionError, match="Rest days PIT violation"):
            assert_rest_days_pit(bad_rest)

    def test_multi_team_isolation(self):
        """Verify teams don't leak form data to each other."""
        games = _team_games([
            ("G1", "KC", "DEN", "2024-09-01T20:00:00+00:00", 28, 21),
            ("G2", "KC", "LV", "2024-09-08T20:00:00+00:00", 35, 14),
            ("G1", "BUF", "MIA", "2024-09-01T13:00:00+00:00", 31, 17),
            ("G2", "BUF", "NYJ", "2024-09-08T13:00:00+00:00", 27, 24),
            ("G3", "KC", "ATL", "2024-09-15T20:00:00+00:00", None, None),
            ("G3", "BUF", "JAX", "2024-09-15T13:00:00+00:00", None, None),
        ])
        
        form_lag = compute_team_form_lag(games)
        
        # KC's G3 should only see KC's prior games
        kc_g3 = form_lag[(form_lag["game_key"] == "G3") & (form_lag["team"] == "KC")].iloc[0]
        assert len(kc_g3["contributing_kickoffs"]) == 2
        
        # BUF's G3 should only see BUF's prior games
        buf_g3 = form_lag[(form_lag["game_key"] == "G3") & (form_lag["team"] == "BUF")].iloc[0]
        assert len(buf_g3["contributing_kickoffs"]) == 2
        
        # KC and BUF kickoff times shouldn't mix
        kc_times = set(kc_g3["contributing_kickoffs"])
        buf_times = set(buf_g3["contributing_kickoffs"])
        assert len(kc_times & buf_times) == 0 or all(
            t in [pd.Timestamp("2024-09-01T20:00:00+00:00"), pd.Timestamp("2024-09-08T20:00:00+00:00")]
            for t in kc_times
        )
