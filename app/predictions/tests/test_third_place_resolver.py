"""
Tests for resolve_user_bracket() third-place slot resolution.

Verifies that R32 "3XXXXX" slots are resolved via the FIFA Annex C table using
the user's ThirdPlaceRanking. Matches must be created in canonical R32_SOURCES
chronological order so the positional resolver assigns them correctly.
"""
from datetime import datetime, timezone

from django.contrib.auth.models import User
from django.test import TestCase

from predictions.models import (
    GroupPrediction, Match, Team,
    ThirdPlaceRanking, ThirdPlaceRankingEntry,
)
from predictions.services.bracket_resolver import R32_SOURCES, resolve_user_bracket
from tournaments.models import Tournament


def _dt(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 6, day, hour, 0, tzinfo=timezone.utc)


_GROUP_LETTERS = list("ABCDEFGHIJKL")


def _make_teams(prefix: str) -> dict[str, dict[str, Team]]:
    """
    Create 3 teams per group (first, second, third) for all 12 groups.
    """
    p = prefix[0].upper()
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
    Create a ThirdPlaceRanking with top_groups (exactly 8) at positions 1-8
    and the remaining 4 groups at positions 9-12.
    """
    assert len(top_groups) == 8
    ranking = ThirdPlaceRanking.objects.create(user=user, tournament=tournament)
    for pos, g in enumerate(top_groups, start=1):
        ThirdPlaceRankingEntry.objects.create(
            ranking=ranking, team=teams[g]["third"], position=pos,
        )
    remaining = [g for g in _GROUP_LETTERS if g not in top_groups]
    for pos, g in enumerate(remaining, start=9):
        ThirdPlaceRankingEntry.objects.create(
            ranking=ranking, team=teams[g]["third"], position=pos,
        )
    return ranking


def _make_r32_matches(start_day: int = 1) -> tuple[list[Match], list[Match]]:
    """
    Create all 16 R32 matches in canonical R32_SOURCES chronological order.
    Returns (third_matches, direct_matches) where third_matches are those at
    positions with a "3XXXXX" away source, direct_matches are the rest.

    All 16 matches must be passed together to resolve_user_bracket so that
    positional indices align with R32_SOURCES.
    """
    third_matches: list[Match] = []
    direct_matches: list[Match] = []
    for i, (hs, as_) in enumerate(R32_SOURCES):
        match = Match.objects.create(
            match_datetime=_dt(start_day + i),
            stage=Match.Stage.ROUND_OF_32,
            home_source=hs, away_source=as_,
        )
        if as_.startswith("3"):
            third_matches.append(match)
        else:
            direct_matches.append(match)
    return third_matches, direct_matches


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
        _make_ranking(self.user, self.tournament, self.teams,
                      top_groups=["E", "F", "G", "H", "I", "J", "K", "L"])
        third_matches, direct_matches = _make_r32_matches()

        all_matches = third_matches + direct_matches
        result = resolve_user_bracket(self.user, self.tournament, all_matches)

        for match in all_matches:
            home, away = result[match.id]
            self.assertIsNotNone(home, f"home is None for match home_source={match.home_source}")
            self.assertIsNotNone(away, f"away is None for match away_source={match.away_source}")

    # ── Test B ─────────────────────────────────────────────────────────────

    def test_B_third_place_slots_none_without_ranking(self):
        """Without a ThirdPlaceRanking the 8 third-place slots are None; direct slots resolve."""
        _make_group_predictions(self.user, self.tournament, self.teams)
        third_matches, direct_matches = _make_r32_matches()

        all_matches = third_matches + direct_matches
        result = resolve_user_bracket(self.user, self.tournament, all_matches)

        for match in third_matches:
            _, away = result[match.id]
            self.assertIsNone(away, f"expected None for {match.away_source} without ranking")

        for match in direct_matches:
            home, away = result[match.id]
            self.assertIsNotNone(home, f"direct home is None: {match.home_source}")
            self.assertIsNotNone(away, f"direct away is None: {match.away_source}")

    # ── Test C ─────────────────────────────────────────────────────────────

    def test_C_no_crash_with_partial_ranking(self):
        """Fewer than 8 ranked thirds → resolver returns None for third slots without crashing."""
        _make_group_predictions(self.user, self.tournament, self.teams)
        ranking = ThirdPlaceRanking.objects.create(user=self.user, tournament=self.tournament)
        for pos, g in enumerate(["A", "B", "C", "D", "E"], start=1):
            ThirdPlaceRankingEntry.objects.create(
                ranking=ranking, team=self.teams[g]["third"], position=pos,
            )
        third_matches, direct_matches = _make_r32_matches()

        result = resolve_user_bracket(
            self.user, self.tournament,
            third_matches + direct_matches,
        )

        for match in third_matches:
            _, away = result[match.id]
            self.assertIsNone(away)

    # ── Test D ─────────────────────────────────────────────────────────────

    def test_D_correct_third_assigned_per_fifa_table_combination_1(self):
        """
        Combination 1 (groups E F G H I J K L qualify) maps thirds to slots
        exactly as FIFA Annex C:

          pos 0 (1E)  combo key "74" → 3rd from group F
          pos 1 (1I)  combo key "77" → 3rd from group G
          pos 6 (1D)  combo key "81" → 3rd from group I
          pos 7 (1G)  combo key "82" → 3rd from group H
          pos 10 (1A) combo key "79" → 3rd from group E
          pos 11 (1L) combo key "80" → 3rd from group K
          pos 14 (1B) combo key "85" → 3rd from group J
          pos 15 (1K) combo key "87" → 3rd from group L
        """
        _make_group_predictions(self.user, self.tournament, self.teams)
        _make_ranking(self.user, self.tournament, self.teams,
                      top_groups=["E", "F", "G", "H", "I", "J", "K", "L"])
        third_matches, direct_matches = _make_r32_matches()

        result = resolve_user_bracket(
            self.user, self.tournament,
            third_matches + direct_matches,
        )

        # Keyed by home_source (unique for each third-place match)
        away_by_home: dict[str, Team] = {
            match.home_source: result[match.id][1]
            for match in third_matches
        }

        expected = {
            "1E": self.teams["F"]["third"],
            "1I": self.teams["G"]["third"],
            "1A": self.teams["E"]["third"],
            "1L": self.teams["K"]["third"],
            "1D": self.teams["I"]["third"],
            "1G": self.teams["H"]["third"],
            "1B": self.teams["J"]["third"],
            "1K": self.teams["L"]["third"],
        }
        for home_src, expected_team in expected.items():
            self.assertEqual(
                away_by_home.get(home_src),
                expected_team,
                msg=f"Wrong third for match {home_src}: expected {expected_team.name}",
            )
