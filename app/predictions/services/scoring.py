"""
Scoring service — Phase 14 prediction model.

Bracket scoring is live (uses Match scores from Football-Data sync).
Group, thirds, and trophy scoring return 0 until official results are
stored (Phase 14g will add result fields and complete those functions).
"""

from predictions.models import (
    BracketPrediction,
    Match,
)

# ── Points per bracket round ─────────────────────────────────────────────────
BRACKET_POINTS = {
    Match.Stage.ROUND_OF_32:  2,
    Match.Stage.ROUND_OF_16:  4,
    Match.Stage.QUARTER_FINAL: 8,
    Match.Stage.SEMI_FINAL:   16,
    Match.Stage.FINAL:        42,
}

# ── Trophy points ────────────────────────────────────────────────────────────
TROPHY_POINTS = {
    "golden_ball":  15,
    "golden_boot":  10,
    "golden_glove":  5,
}

# ── Group scoring ────────────────────────────────────────────────────────────
GROUP_POINTS = {1: 5, 2: 3, 3: 2}


def _bracket_actual_winner(match):
    """
    Return the actual winning Team of a finished knockout match, or None.
    Tied scores (penalty shootouts) cannot be resolved from scores alone.
    """
    if match.status != "FINISHED":
        return None
    if match.home_score is None or match.away_score is None:
        return None
    if match.home_score > match.away_score:
        return match.home_team
    if match.away_score > match.home_score:
        return match.away_team
    return None


def score_bracket(user, tournament):
    """Points for BracketPredictions that match actual match results."""
    predictions = (
        BracketPrediction.objects
        .filter(user=user, tournament=tournament)
        .select_related("match__home_team", "match__away_team", "predicted_winner")
    )
    total = 0
    for pred in predictions:
        actual = _bracket_actual_winner(pred.match)
        if actual is not None and pred.predicted_winner_id == actual.pk:
            total += BRACKET_POINTS.get(pred.match.stage, 0)
    return total


def score_groups(user, tournament):  # noqa: ARG001
    """
    Points for GroupPredictions vs actual group standings.
    Requires official group-stage results — returns 0 until Phase 14g.
    """
    return 0


def score_thirds(user, tournament):  # noqa: ARG001
    """
    Points for ThirdPlaceRanking vs actual third-place qualifiers.
    Requires official 3rd-place results — returns 0 until Phase 14g.
    """
    return 0


def score_trophies(user, tournament):  # noqa: ARG001
    """
    Points for SpecialPredictions vs official trophy winners.
    Requires storing official results — returns 0 until Phase 14g.
    """
    return 0


def compute_user_points(user, tournament):
    """Total points for a user in a tournament across all prediction categories."""
    return (
        score_groups(user, tournament)
        + score_thirds(user, tournament)
        + score_bracket(user, tournament)
        + score_trophies(user, tournament)
    )
