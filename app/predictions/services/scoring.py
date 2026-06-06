"""
Scoring service for the Maldinis prediction system.

All three scoreable categories are computed on-demand from Match results:

  - Groups  (GroupPrediction):      5/3/2 pts per correct 1st/2nd/3rd.
  - Thirds  (ThirdPlaceRanking):    2 pts per team in actual top-8 thirds
                                    + 1 pt bonus for exact position.
  - Bracket (BracketPrediction):    2/4/8/16/42 pts by round.

SpecialPrediction (trophies) is kept in the DB but excluded from scoring.

Limitations
-----------
- Group tiebreakers: simplified to (pts DESC, goal_diff DESC, goals_for DESC).
  FIFA 2026 uses head-to-head as first tiebreaker — not yet implemented.
- Knockout matches decided by penalty shootout store equal fullTime scores
  (e.g. 1-1 at 90 min); _bracket_actual_winner() returns None for those
  until the sync command is extended to store extra-time / penalty results.
"""

from predictions.models import (
    BracketPrediction,
    GroupPrediction,
    Match,
    ThirdPlaceRanking,
)

# ── Point tables ──────────────────────────────────────────────────────────────
GROUP_POINTS = {1: 5, 2: 3, 3: 2}

BRACKET_POINTS = {
    Match.Stage.ROUND_OF_32:   2,
    Match.Stage.ROUND_OF_16:   4,
    Match.Stage.QUARTER_FINAL: 8,
    Match.Stage.SEMI_FINAL:    16,
    Match.Stage.FINAL:         42,
}

THIRDS_QUALIFY_PTS    = 2
THIRDS_POSITION_BONUS = 1

_GROUPS = list("ABCDEFGHIJKL")


# ── Actual-result helpers ─────────────────────────────────────────────────────

def _group_standings(group_letter):
    """
    Return the actual final standings for a group as a list of dicts
    [{team, pts, gf, ga}] sorted by (pts DESC, gd DESC, gf DESC).

    Returns None if any match in the group is not yet FINISHED, or if the
    group has no matches at all.
    """
    matches = list(
        Match.objects
        .filter(stage=Match.Stage.GROUP, group=group_letter)
        .select_related("home_team", "away_team")
    )
    if not matches:
        return None

    for m in matches:
        if m.status != "FINISHED" or m.home_score is None or m.away_score is None:
            return None

    teams: dict = {}
    for m in matches:
        for team in (m.home_team, m.away_team):
            if team and team.pk not in teams:
                teams[team.pk] = {"team": team, "pts": 0, "gf": 0, "ga": 0}

    for m in matches:
        if not m.home_team or not m.away_team:
            continue
        hs, as_ = m.home_score, m.away_score
        teams[m.home_team.pk]["gf"] += hs
        teams[m.home_team.pk]["ga"] += as_
        teams[m.away_team.pk]["gf"] += as_
        teams[m.away_team.pk]["ga"] += hs
        if hs > as_:
            teams[m.home_team.pk]["pts"] += 3
        elif as_ > hs:
            teams[m.away_team.pk]["pts"] += 3
        else:
            teams[m.home_team.pk]["pts"] += 1
            teams[m.away_team.pk]["pts"] += 1

    return sorted(
        teams.values(),
        key=lambda s: (s["pts"], s["gf"] - s["ga"], s["gf"]),
        reverse=True,
    )


def _actual_thirds_ranking():
    """
    Return [{position, team}] for the 8 best third-place teams, sorted by
    (pts DESC, gd DESC, gf DESC) across all completed groups.

    Uses the same simplified tiebreaker as _group_standings.
    Groups that are not yet fully finished are excluded.
    """
    thirds: list = []
    for g in _GROUPS:
        standings = _group_standings(g)
        if standings and len(standings) >= 3:
            thirds.append(standings[2])

    thirds.sort(key=lambda s: (s["pts"], s["gf"] - s["ga"], s["gf"]), reverse=True)

    return [
        {"position": pos, "team": entry["team"]}
        for pos, entry in enumerate(thirds[:8], start=1)
    ]


def _bracket_actual_winner(match):
    """
    Return the actual winning Team of a finished knockout match, or None.

    Tied fullTime scores (extra-time / penalty outcomes) cannot be resolved
    from fullTime data alone; those matches return None until the sync is
    extended to also store regularTime + extraTime + penalties breakdowns.
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


# ── Category scorers ──────────────────────────────────────────────────────────

def score_groups(user, tournament):
    """Points earned by the user's GroupPredictions against actual standings."""
    preds = {
        gp.group: gp
        for gp in GroupPrediction.objects.filter(
            user=user, tournament=tournament
        ).select_related("first_team", "second_team", "third_team")
    }

    total = 0
    for g in _GROUPS:
        pred = preds.get(g)
        if not pred:
            continue
        standings = _group_standings(g)
        if not standings or len(standings) < 3:
            continue

        actual    = [standings[0]["team"], standings[1]["team"], standings[2]["team"]]
        predicted = [pred.first_team,      pred.second_team,     pred.third_team]

        for pos, (actual_team, pred_team) in enumerate(zip(actual, predicted), start=1):
            if pred_team and actual_team and pred_team.pk == actual_team.pk:
                total += GROUP_POINTS[pos]

    return total


def score_thirds(user, tournament):
    """
    Points earned by the user's ThirdPlaceRanking.

    +2 pts per team that made the actual top-8.
    +1 pt bonus if the predicted position matches the actual position.
    """
    try:
        ranking = ThirdPlaceRanking.objects.prefetch_related(
            "entries__team"
        ).get(user=user, tournament=tournament)
    except ThirdPlaceRanking.DoesNotExist:
        return 0

    actual_ranking = _actual_thirds_ranking()
    if not actual_ranking:
        return 0

    actual_pos_by_team = {entry["team"].pk: entry["position"] for entry in actual_ranking}
    actual_team_ids    = set(actual_pos_by_team)

    total = 0
    for entry in ranking.entries.all():
        if entry.team_id in actual_team_ids:
            total += THIRDS_QUALIFY_PTS
            if entry.position == actual_pos_by_team[entry.team_id]:
                total += THIRDS_POSITION_BONUS

    return total


def score_bracket(user, tournament):
    """Points earned by the user's BracketPredictions against match results."""
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


# ── Public API ────────────────────────────────────────────────────────────────

def compute_user_score(user, tournament):
    """
    Compute a user's score breakdown for a tournament.

    Returns:
        {
            "groups":  int,   # pts from group predictions
            "thirds":  int,   # pts from third-place ranking
            "bracket": int,   # pts from bracket predictions
            "total":   int,   # sum of all categories
        }
    """
    groups_pts  = score_groups(user, tournament)
    thirds_pts  = score_thirds(user, tournament)
    bracket_pts = score_bracket(user, tournament)
    return {
        "groups":  groups_pts,
        "thirds":  thirds_pts,
        "bracket": bracket_pts,
        "total":   groups_pts + thirds_pts + bracket_pts,
    }


def compute_user_points(user, tournament):
    """Backward-compatible alias — returns compute_user_score()['total']."""
    return compute_user_score(user, tournament)["total"]
