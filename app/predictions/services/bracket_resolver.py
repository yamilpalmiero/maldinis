from __future__ import annotations

import logging
from collections.abc import Iterable

from django.contrib.auth.models import User

from predictions.data.third_place_combinations import THIRD_PLACE_COMBINATIONS
from predictions.models import (
    BracketPrediction, GroupPrediction, Match, Team, ThirdPlaceRankingEntry,
)
from tournaments.models import Tournament

logger = logging.getLogger(__name__)

# Maps the winner-group letter (from home_source "1X") to the key used in
# THIRD_PLACE_COMBINATIONS for that R32 third-place slot.
# Derived from FIFA 2026 bracket: the 8 R32 "vs best third" slots each host
# a specific group winner (1A, 1B, 1D, 1E, 1G, 1I, 1K, 1L).
_WINNER_GROUP_TO_COMBO_KEY: dict[str, str] = {
    "A": "79", "B": "85", "D": "81", "E": "74",
    "G": "82", "I": "77", "K": "87", "L": "80",
}


def resolve_user_bracket(
    user: User,
    tournament: Tournament,
    knockout_matches: Iterable[Match],
) -> dict[int, tuple[Team | None, Team | None]]:
    """
    Returns {match.id: (home_team, away_team)} for each match in
    knockout_matches, resolved from the user's group and bracket predictions.

    Either team may be None when a prediction is missing.

    Makes at most 3 DB queries. The caller must supply knockout_matches in
    chronological order (which is topological for the bracket dependency chain).
    """
    matches = list(knockout_matches)

    # Query 1: all group predictions for this user+tournament
    group_map: dict[str, GroupPrediction] = {
        gp.group: gp
        for gp in GroupPrediction.objects.filter(
            user=user, tournament=tournament
        ).select_related("first_team", "second_team", "third_team")
    }

    # Query 2: all bracket predictions for this user+tournament
    bracket_map: dict[int, Team] = {
        bp.match_id: bp.predicted_winner
        for bp in BracketPrediction.objects.filter(
            user=user, tournament=tournament
        ).select_related("predicted_winner")
    }

    # Query 3: third-place slot map for "3XXXXX" away sources (R32 only)
    third_slot_map = _build_third_slot_map(user, tournament, group_map, matches)

    resolved: dict[int, tuple[Team | None, Team | None]] = {}

    for match in matches:
        home = _resolve_source(match.home_source, group_map, bracket_map, resolved)

        if match.away_source.startswith("3") and len(match.away_source) > 2:
            away = third_slot_map.get(str(match.id))
        else:
            away = _resolve_source(match.away_source, group_map, bracket_map, resolved)

        resolved[match.id] = (home, away)

    return resolved


def _build_third_slot_map(
    user: User,
    tournament: Tournament,
    group_map: dict[str, GroupPrediction],
    matches: list[Match],
) -> dict[str, Team]:
    """
    Returns {str(match.id): team} for R32 slots with "3XXXXX" away sources,
    using the user's top-8 ranked thirds and the FIFA Annex C table.

    Returns empty dict if the user has fewer than 8 ranked thirds, or if the
    resulting group combination is absent from THIRD_PLACE_COMBINATIONS.
    """
    # Query 3: top 8 ranked thirds ordered by position
    entries = list(
        ThirdPlaceRankingEntry.objects
        .filter(ranking__user=user, ranking__tournament=tournament)
        .order_by("position")
        .select_related("team")[:8]
    )
    if len(entries) < 8:
        return {}

    # Map team_id → source group (from group_map third_team predictions)
    team_to_group: dict[int, str] = {
        gp.third_team_id: gp.group
        for gp in group_map.values()
        if gp.third_team_id is not None
    }

    # Determine the 8 qualifying groups from the ranked entries
    qualified_groups_list: list[str] = []
    for entry in entries:
        group = team_to_group.get(entry.team_id)
        if group is None:
            return {}  # ranked third not found in group predictions
        qualified_groups_list.append(group)

    qualified_groups = frozenset(qualified_groups_list)
    if len(qualified_groups) != 8:
        return {}  # duplicate groups — data inconsistency

    combo = THIRD_PLACE_COMBINATIONS.get(qualified_groups)
    if combo is None:
        logger.warning(
            "Third-place combination %s not in THIRD_PLACE_COMBINATIONS "
            "(user=%s, tournament=%s)",
            sorted(qualified_groups), user.pk, tournament.pk,
        )
        return {}

    # Build group → third_team from group_map
    third_team_by_group: dict[str, Team] = {
        gp.group: gp.third_team
        for gp in group_map.values()
        if gp.third_team is not None
    }

    # For each R32 match with a "3XXXXX" away source, map match.id → assigned third
    slot_map: dict[str, Team] = {}
    for match in matches:
        if not (match.away_source.startswith("3") and len(match.away_source) > 2):
            continue
        # home_source is "1X" — extract the winner group letter
        if len(match.home_source) != 2 or match.home_source[0] != "1":
            continue
        winner_group = match.home_source[1]
        combo_key = _WINNER_GROUP_TO_COMBO_KEY.get(winner_group)
        if combo_key is None:
            continue
        src_group = combo.get(combo_key)
        if src_group is None:
            continue
        team = third_team_by_group.get(src_group)
        if team is not None:
            slot_map[str(match.id)] = team

    return slot_map


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
