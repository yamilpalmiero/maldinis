"""
Tests for resolve_user_bracket() third-place slot resolution (fase 14e paso 3.5b).

Verifies that "3XXXXX" R32 slots are resolved via the FIFA Annex C table using
the user's ThirdPlaceRanking, instead of always returning None.
"""
from datetime import datetime, timezone

from django.contrib.auth.models import User
from django.test import TestCase

from predictions.models import (
    GroupPrediction, Match, Team,
    ThirdPlaceRanking, ThirdPlaceRankingEntry,
)
from predictions.services.bracket_resolver import resolve_user_bracket
from tournaments.models import Tournament


def _dt(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 6, day, hour, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GROUP_LETTERS = list("ABCDEFGHIJKL")


def _make_teams(prefix: str) -> dict[str, dict[str, Team]]:
    """
    Create 3 teams per group (first, second, third) for all 12 groups.
    Returns {group: {"first": Team, "second": Team, "third": Team}}.
    Team.code is varchar(3), so codes use one letter from prefix + group + position.
    """
    p = prefix[0].upper()  # single char prefix to stay within 3-char limit
    teams: dict[str, dict[str, Team]] = {}
    for g in _GROUP_LETTERS:
        teams[g] = {
            "first":  Team.objects.create(name=f"{p}{g}1", code=f"{p}{g}1"),
            "second": Team.objects.create(name=f"{p}{g}2", code=f"{p}{g}2"),
            "third":  Team.objects.create(name=f"{p}{g}3", code=f"{p}{g}3"),
        }
    return teams


def _make_group_predictions(user, tournament, teams: dict) -> None:
    for g in _GROUP_LETTERS:
        GroupPrediction.objects.create(
            user=user, tournament=tournament, group=g,
            first_team=teams[g]["first"],
            second_team=teams[g]["second"],
            third_team=teams[g]["third"],
        )


def _make_ranking(user, tournament, teams: dict, top_groups: list[str]) -> ThirdPlaceRanking:
    """
    Create a ThirdPlaceRanking where thirds from top_groups are ranked 1-N
    and all remaining groups' thirds follow (to fill 12 entries).
    top_groups must have exactly 8 entries (the qualifying thirds).
    """
    assert len(top_groups) == 8
    ranking = ThirdPlaceRanking.objects.create(user=user, tournament=tournament)
    # The 8 qualifying thirds at positions 1-8
    for pos, g in enumerate(top_groups, start=1):
        ThirdPlaceRankingEntry.objects.create(
            ranking=ranking, team=teams[g]["third"], position=pos,
        )
    # Remaining 4 at positions 9-12
    remaining = [g for g in _GROUP_LETTERS if g not in top_groups]
    for pos, g in enumerate(remaining, start=9):
        ThirdPlaceRankingEntry.objects.create(
            ranking=ranking, team=teams[g]["third"], position=pos,
        )
    return ranking


# R32 third-place matches: (home_source, away_source) pairs for the 8 slots.
# home_source determines which combo key to use; away_source must start with "3".
_R32_THIRD_PLACE_SOURCES = [
    ("1E", "3ABCDF"),   # combo key "74"
    ("1I", "3CDFGH"),   # combo key "77"
    ("1A", "3CEFHI"),   # combo key "79"
    ("1L", "3EHIJK"),   # combo key "80"
    ("1D", "3BEFIJ"),   # combo key "81"
    ("1G", "3AEHIJ"),   # combo key "82"
    ("1B", "3EFGIJ"),   # combo key "85"
    ("1K", "3DEIJL"),   # combo key "87"
]

# R32 "1X vs 2Y" matches (no third-place dependency)
_R32_DIRECT_SOURCES = [
    ("2A", "2B"),
    ("1F", "2C"),
    ("2K", "2L"),
    ("1H", "2J"),
    ("1C", "2F"),
    ("2E", "2I"),
    ("2D", "2G"),
    ("1J", "2H"),
]


def _make_r32_matches(start_day: int = 1) -> tuple[list[Match], list[Match]]:
    """Create the 8 third-place and 8 direct R32 matches. Returns (third_matches, direct_matches)."""
    third_matches = []
    for i, (hs, as_) in enumerate(_R32_THIRD_PLACE_SOURCES):
        third_matches.append(Match.objects.create(
            match_datetime=_dt(start_day + i),
            stage=Match.Stage.ROUND_OF_32,
            home_source=hs, away_source=as_,
        ))
    direct_matches = []
    for i, (hs, as_) in enumerate(_R32_DIRECT_SOURCES):
        direct_matches.append(Match.objects.create(
            match_datetime=_dt(start_day + 8 + i),
            stage=Match.Stage.ROUND_OF_32,
            home_source=hs, away_source=as_,
        ))
    return third_matches, direct_matches


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class ThirdPlaceResolverTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("resolver_tester")
        cls.tournament = Tournament.objects.create(name="Resolver Test", created_by=cls.user)

    def setUp(self):
        """Each test gets fresh teams, predictions, and matches."""
        self.teams = _make_teams(self._testMethodName[:4])

    # ── Test A ─────────────────────────────────────────────────────────────

    def test_A_all_r32_slots_resolved_when_ranking_complete(self):
        """All 16 R32 slots resolve to non-None when groups + ranking are complete."""
        _make_group_predictions(self.user, self.tournament, self.teams)
        # Use groups E-L as the top 8 (combination 1)
        _make_ranking(self.user, self.tournament, self.teams,
                      top_groups=["E", "F", "G", "H", "I", "J", "K", "L"])
        third_matches, direct_matches = _make_r32_matches()

        all_matches = sorted(third_matches + direct_matches, key=lambda m: m.match_datetime)
        result = resolve_user_bracket(self.user, self.tournament, all_matches)

        for match in third_matches + direct_matches:
            home, away = result[match.id]
            self.assertIsNotNone(home, f"home is None for match home_source={match.home_source}")
            self.assertIsNotNone(away, f"away is None for match away_source={match.away_source}")

    # ── Test B ─────────────────────────────────────────────────────────────

    def test_B_third_place_slots_none_without_ranking(self):
        """Without a ThirdPlaceRanking the 8 third-place slots are None; direct slots resolve."""
        _make_group_predictions(self.user, self.tournament, self.teams)
        # No ThirdPlaceRanking created
        third_matches, direct_matches = _make_r32_matches(start_day=1)

        all_matches = sorted(third_matches + direct_matches, key=lambda m: m.match_datetime)
        result = resolve_user_bracket(self.user, self.tournament, all_matches)

        # Third-place slots → away must be None
        for match in third_matches:
            _, away = result[match.id]
            self.assertIsNone(away, f"expected None for {match.away_source} without ranking")

        # Direct slots → both home and away resolve
        for match in direct_matches:
            home, away = result[match.id]
            self.assertIsNotNone(home, f"direct home is None: {match.home_source}")
            self.assertIsNotNone(away, f"direct away is None: {match.away_source}")

    # ── Test C ─────────────────────────────────────────────────────────────

    def test_C_no_crash_with_partial_ranking(self):
        """Fewer than 8 ranked thirds → resolver returns None for third slots without crashing."""
        _make_group_predictions(self.user, self.tournament, self.teams)
        ranking = ThirdPlaceRanking.objects.create(user=self.user, tournament=self.tournament)
        # Only 5 entries (fewer than 8)
        for pos, g in enumerate(["A", "B", "C", "D", "E"], start=1):
            ThirdPlaceRankingEntry.objects.create(
                ranking=ranking, team=self.teams[g]["third"], position=pos,
            )
        third_matches, _ = _make_r32_matches(start_day=1)

        result = resolve_user_bracket(
            self.user, self.tournament,
            sorted(third_matches, key=lambda m: m.match_datetime),
        )

        for match in third_matches:
            _, away = result[match.id]
            self.assertIsNone(away)

    # ── Test D ─────────────────────────────────────────────────────────────

    def test_D_correct_third_assigned_per_fifa_table_combination_1(self):
        """
        Combination 1 (groups E F G H I J K L qualify) maps thirds to slots
        exactly as Wikipedia row 1 / FIFA Annex C:

          combo key "74" (1E match) → 3rd from group F
          combo key "77" (1I match) → 3rd from group G
          combo key "79" (1A match) → 3rd from group E
          combo key "80" (1L match) → 3rd from group K
          combo key "81" (1D match) → 3rd from group I
          combo key "82" (1G match) → 3rd from group H
          combo key "85" (1B match) → 3rd from group J
          combo key "87" (1K match) → 3rd from group L
        """
        _make_group_predictions(self.user, self.tournament, self.teams)
        _make_ranking(self.user, self.tournament, self.teams,
                      top_groups=["E", "F", "G", "H", "I", "J", "K", "L"])
        third_matches, _ = _make_r32_matches(start_day=1)

        result = resolve_user_bracket(
            self.user, self.tournament,
            sorted(third_matches, key=lambda m: m.match_datetime),
        )

        # Build lookup: home_source → away team from result
        away_by_home: dict[str, Team] = {
            match.home_source: result[match.id][1]
            for match in third_matches
        }

        expected = {
            "1E": self.teams["F"]["third"],   # combo key 74 → group F
            "1I": self.teams["G"]["third"],   # combo key 77 → group G
            "1A": self.teams["E"]["third"],   # combo key 79 → group E
            "1L": self.teams["K"]["third"],   # combo key 80 → group K
            "1D": self.teams["I"]["third"],   # combo key 81 → group I
            "1G": self.teams["H"]["third"],   # combo key 82 → group H
            "1B": self.teams["J"]["third"],   # combo key 85 → group J
            "1K": self.teams["L"]["third"],   # combo key 87 → group L
        }
        for home_src, expected_team in expected.items():
            self.assertEqual(
                away_by_home.get(home_src),
                expected_team,
                msg=f"Wrong third for match {home_src}: expected {expected_team.name}",
            )
