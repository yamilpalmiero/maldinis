from __future__ import annotations

from collections.abc import Iterable

from django.contrib.auth.models import User

from predictions.models import BracketPrediction, GroupPrediction, Match, Team
from tournaments.models import Tournament


def resolve_user_bracket(
    user: User,
    tournament: Tournament,
    knockout_matches: Iterable[Match],
) -> dict[int, tuple[Team | None, Team | None]]:
    """
    Returns {match.id: (home_team, away_team)} for each match in
    knockout_matches, resolved from the user's group and bracket predictions.

    Either team may be None when a prediction is missing or the slot is a
    third-place code (e.g. "3ABCDF") — ~495 possible combinations, not
    resolved here; shown as a placeholder in the UI.

    Makes exactly 2 DB queries. The caller must supply knockout_matches in
    chronological order (which is topological for the bracket dependency chain).
    """
    # Query 1: all group predictions for this user+tournament
    group_map: dict[str, GroupPrediction] = {
        gp.group: gp
        for gp in GroupPrediction.objects.filter(
            user=user, tournament=tournament
        ).select_related("first_team", "second_team")
    }

    # Query 2: all bracket predictions for this user+tournament
    bracket_map: dict[int, Team] = {
        bp.match_id: bp.predicted_winner
        for bp in BracketPrediction.objects.filter(
            user=user, tournament=tournament
        ).select_related("predicted_winner")
    }

    resolved: dict[int, tuple[Team | None, Team | None]] = {}

    for match in knockout_matches:
        home = _resolve_source(match.home_source, group_map, bracket_map, resolved)
        away = _resolve_source(match.away_source, group_map, bracket_map, resolved)
        resolved[match.id] = (home, away)

    return resolved


def _resolve_source(
    source: str,
    group_map: dict[str, GroupPrediction],
    bracket_map: dict[int, Team],
    resolved: dict[int, tuple[Team | None, Team | None]],
) -> Team | None:
    if not source:
        return None

    # "1X" / "2X" — group winner or runner-up
    if len(source) == 2 and source[0] in "12" and source[1].isalpha():
        gp = group_map.get(source[1])
        if gp is None:
            return None
        return gp.first_team if source[0] == "1" else gp.second_team

    # "3XXXXX" — best third from subset of groups (~495 combinations, placeholder)
    if source.startswith("3") and len(source) > 2:
        return None

    # "WXX" — winner of match XX (user's bracket prediction)
    if source.startswith("W"):
        return bracket_map.get(int(source[1:]))

    # "LXX" — loser of match XX
    if source.startswith("L"):
        match_id = int(source[1:])
        winner = bracket_map.get(match_id)
        if winner is None:
            return None
        prior = resolved.get(match_id)
        if prior is None:
            return None
        home, away = prior
        if home is not None and winner.pk == home.pk:
            return away
        if away is not None and winner.pk == away.pk:
            return home
        # Inconsistent state: predicted winner not among the resolved teams
        return None

    return None
