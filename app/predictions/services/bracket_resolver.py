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

# FIFA 2026 R32 bracket structure (M73–M88). Position index = chronological order.
# home_src: "1X" (group X winner) or "2X" (group X runner-up)
# away_src: "2X" or "3XXXXX" (third-place slot keyed by qualifying groups)
R32_SOURCES: list[tuple[str, str]] = [
    ("1E", "3ABCDF"), ("1I", "3CDFGH"), ("2A", "2B"),    ("1F", "2C"),
    ("2K", "2L"),     ("1H", "2J"),     ("1D", "3BEFIJ"), ("1G", "3AEHIJ"),
    ("1C", "2F"),     ("2E", "2I"),     ("1A", "3CEFHI"), ("1L", "3EHIJK"),
    ("1J", "2H"),     ("2D", "2G"),     ("1B", "3EFGIJ"), ("1K", "3DEIJL"),
]

# Maps winner-group letter (from R32_SOURCES home_src "1X") to the key used in
# THIRD_PLACE_COMBINATIONS for that slot.
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
    Returns {match.id: (home_team, away_team)} for each knockout match,
    resolved from the user's group and bracket predictions.

    Uses hardcoded FIFA 2026 R32 structure — does not read home_source/away_source from DB.
    Matches are sorted chronologically within each stage to determine positions.
    Makes exactly 3 DB queries.
    """
    matches = sorted(knockout_matches, key=lambda m: m.match_datetime)

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

    # Query 3: third-place slot map for R32 slots with "3XXXXX" away sources
    third_slot_map = _build_third_slot_map(user, tournament, group_map)

    # Group matches by stage, preserving chronological order (already sorted above)
    stage_matches: dict = {}
    for m in matches:
        stage_matches.setdefault(m.stage, []).append(m)

    r32 = stage_matches.get(Match.Stage.ROUND_OF_32, [])
    r16 = stage_matches.get(Match.Stage.ROUND_OF_16, [])
    qf  = stage_matches.get(Match.Stage.QUARTER_FINAL, [])
    sf  = stage_matches.get(Match.Stage.SEMI_FINAL, [])
    fin = stage_matches.get(Match.Stage.FINAL, [])

    resolved: dict[int, tuple[Team | None, Team | None]] = {}

    # R32: positional source from hardcoded R32_SOURCES
    for i, match in enumerate(r32):
        if i >= len(R32_SOURCES):
            resolved[match.id] = (None, None)
            continue
        home_src, away_src = R32_SOURCES[i]
        home = _resolve_group_source(home_src, group_map)
        away = third_slot_map.get(i) if away_src.startswith("3") else _resolve_group_source(away_src, group_map)
        resolved[match.id] = (home, away)

    # R16, QF, SF: positional pairing — match[i] receives winners of prev[i*2] and prev[i*2+1]
    for current, prev in [(r16, r32), (qf, r16), (sf, qf)]:
        for i, match in enumerate(current):
            home = bracket_map.get(prev[i * 2].id) if i * 2 < len(prev) else None
            away = bracket_map.get(prev[i * 2 + 1].id) if i * 2 + 1 < len(prev) else None
            resolved[match.id] = (home, away)

    # Final: winners of sf[0] and sf[1]
    for match in fin:
        home = bracket_map.get(sf[0].id) if sf else None
        away = bracket_map.get(sf[1].id) if len(sf) > 1 else None
        resolved[match.id] = (home, away)

    return resolved


def _resolve_group_source(source: str, group_map: dict) -> Team | None:
    """Resolve '1X' (winner) or '2X' (runner-up) to a team from group_map."""
    if len(source) == 2 and source[0] in "12" and source[1].isalpha():
        gp = group_map.get(source[1])
        if gp is None:
            return None
        return gp.first_team if source[0] == "1" else gp.second_team
    return None


def _build_third_slot_map(
    user: User,
    tournament: Tournament,
    group_map: dict[str, GroupPrediction],
) -> dict[int, Team]:
    """
    Returns {r32_position_index: team} for each R32 slot with a third-place away source,
    using the user's ThirdPlaceRanking and FIFA Annex C combinations.

    Returns empty dict if fewer than 8 thirds are ranked or the combination is unknown.
    """
    # Query 3
    entries = list(
        ThirdPlaceRankingEntry.objects
        .filter(ranking__user=user, ranking__tournament=tournament)
        .order_by("position")
        .select_related("team")[:8]
    )
    if len(entries) < 8:
        return {}

    team_to_group: dict[int, str] = {
        gp.third_team_id: gp.group
        for gp in group_map.values()
        if gp.third_team_id is not None
    }

    qualified_groups_list: list[str] = []
    for entry in entries:
        group = team_to_group.get(entry.team_id)
        if group is None:
            return {}
        qualified_groups_list.append(group)

    qualified_groups = frozenset(qualified_groups_list)
    if len(qualified_groups) != 8:
        return {}

    combo = THIRD_PLACE_COMBINATIONS.get(qualified_groups)
    if combo is None:
        logger.warning(
            "Third-place combination %s not in THIRD_PLACE_COMBINATIONS "
            "(user=%s, tournament=%s)",
            sorted(qualified_groups), user.pk, tournament.pk,
        )
        return {}

    third_team_by_group: dict[str, Team] = {
        gp.group: gp.third_team
        for gp in group_map.values()
        if gp.third_team is not None
    }

    slot_map: dict[int, Team] = {}
    for i, (home_src, away_src) in enumerate(R32_SOURCES):
        if not away_src.startswith("3"):
            continue
        if len(home_src) != 2 or home_src[0] != "1":
            continue
        winner_group = home_src[1]
        combo_key = _WINNER_GROUP_TO_COMBO_KEY.get(winner_group)
        if combo_key is None:
            continue
        src_group = combo.get(combo_key)
        if src_group is None:
            continue
        team = third_team_by_group.get(src_group)
        if team is not None:
            slot_map[i] = team

    return slot_map
