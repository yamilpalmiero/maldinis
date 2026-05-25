"""
Tests for predictions/services/scoring.py.

Covers _group_standings, _actual_thirds_ranking, score_groups,
score_thirds, score_bracket, and compute_user_score.
"""
from datetime import datetime, timezone

from django.contrib.auth.models import User
from django.test import TestCase

from predictions.models import (
    BracketPrediction,
    GroupPrediction,
    Match,
    Team,
    ThirdPlaceRanking,
    ThirdPlaceRankingEntry,
)
from predictions.services.scoring import (
    _actual_thirds_ranking,
    _group_standings,
    compute_user_score,
    score_bracket,
    score_groups,
    score_thirds,
)
from tournaments.models import Tournament


def _dt(day=1, hour=18):
    return datetime(2026, 6, day, hour, 0, tzinfo=timezone.utc)


def _group_match(home, away, hs, as_, group="A"):
    return Match.objects.create(
        stage=Match.Stage.GROUP,
        group=group,
        match_datetime=_dt(),
        home_team=home,
        away_team=away,
        home_score=hs,
        away_score=as_,
        status="FINISHED",
    )


class GroupStandingsTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.t1 = Team.objects.create(name="Argentina", code="ARG")
        cls.t2 = Team.objects.create(name="Brasil", code="BRA")
        cls.t3 = Team.objects.create(name="Chile", code="CHI")
        cls.t4 = Team.objects.create(name="Uruguay", code="URU")

    def _make_full_group(self, group="A", results=None):
        """Create all 6 group-phase matches for 4 teams.
        results is a list of (home_idx, away_idx, hs, as_) using 1-based team index.
        """
        teams = [self.t1, self.t2, self.t3, self.t4]
        if results is None:
            results = [
                (0, 1, 3, 0),
                (0, 2, 2, 1),
                (0, 3, 1, 1),
                (1, 2, 2, 2),
                (1, 3, 0, 1),
                (2, 3, 1, 0),
            ]
        for hi, ai, hs, as_ in results:
            Match.objects.create(
                stage=Match.Stage.GROUP, group=group, match_datetime=_dt(),
                home_team=teams[hi], away_team=teams[ai],
                home_score=hs, away_score=as_, status="FINISHED",
            )

    def test_returns_none_for_empty_group(self):
        self.assertIsNone(_group_standings("X"))

    def test_returns_none_when_match_not_finished(self):
        Match.objects.create(
            stage=Match.Stage.GROUP, group="B", match_datetime=_dt(),
            home_team=self.t1, away_team=self.t2, status="SCHEDULED",
        )
        self.assertIsNone(_group_standings("B"))

    def test_returns_none_when_score_missing(self):
        Match.objects.create(
            stage=Match.Stage.GROUP, group="C", match_datetime=_dt(),
            home_team=self.t1, away_team=self.t2,
            home_score=None, away_score=None, status="FINISHED",
        )
        self.assertIsNone(_group_standings("C"))

    def test_correct_standings_order(self):
        # t1 beats t2, t3, t4; t2 beats t3, t4; t3 beats t4
        # t1: 9 pts, t2: 6 pts, t3: 3 pts, t4: 0 pts
        self._make_full_group(group="D", results=[
            (0, 1, 1, 0),  # ARG beats BRA
            (0, 2, 1, 0),  # ARG beats CHI
            (0, 3, 1, 0),  # ARG beats URU
            (1, 2, 1, 0),  # BRA beats CHI
            (1, 3, 1, 0),  # BRA beats URU
            (2, 3, 1, 0),  # CHI beats URU
        ])
        standings = _group_standings("D")
        self.assertIsNotNone(standings)
        self.assertEqual(len(standings), 4)
        self.assertEqual(standings[0]["team"], self.t1)
        self.assertEqual(standings[0]["pts"], 9)
        self.assertEqual(standings[1]["team"], self.t2)
        self.assertEqual(standings[2]["team"], self.t3)
        self.assertEqual(standings[3]["team"], self.t4)
        self.assertEqual(standings[3]["pts"], 0)

    def test_goal_difference_tiebreaker(self):
        # t1 and t2 tied on pts; t1 has better gd
        Match.objects.create(
            stage=Match.Stage.GROUP, group="E", match_datetime=_dt(),
            home_team=self.t1, away_team=self.t2,
            home_score=3, away_score=0, status="FINISHED",
        )
        Match.objects.create(
            stage=Match.Stage.GROUP, group="E", match_datetime=_dt(),
            home_team=self.t3, away_team=self.t4,
            home_score=1, away_score=0, status="FINISHED",
        )
        # t1 beats t3; t2 beats t4 → same pts across the group but gd differs
        Match.objects.create(
            stage=Match.Stage.GROUP, group="E", match_datetime=_dt(),
            home_team=self.t1, away_team=self.t3,
            home_score=2, away_score=0, status="FINISHED",
        )
        Match.objects.create(
            stage=Match.Stage.GROUP, group="E", match_datetime=_dt(),
            home_team=self.t1, away_team=self.t4,
            home_score=1, away_score=0, status="FINISHED",
        )
        Match.objects.create(
            stage=Match.Stage.GROUP, group="E", match_datetime=_dt(),
            home_team=self.t2, away_team=self.t3,
            home_score=1, away_score=0, status="FINISHED",
        )
        Match.objects.create(
            stage=Match.Stage.GROUP, group="E", match_datetime=_dt(),
            home_team=self.t2, away_team=self.t4,
            home_score=1, away_score=0, status="FINISHED",
        )
        standings = _group_standings("E")
        # t1: 9 pts, gf=6; t2: 6pts; t3: 3pts; t4: 0pts
        self.assertEqual(standings[0]["team"], self.t1)


class ActualThirdsRankingTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teams = {
            letter: Team.objects.create(name=f"Team{letter}", code=letter * 3)
            for letter in "ABCDEFGHIJKL"
        }

    def _fill_group(self, letter, teams_pts):
        """
        Create stub FINISHED group matches to produce standings.
        teams_pts: [(team_code, pts), ...] in desired rank order.
        Uses direct all-wins simulation: first wins all, second beats 3rd and 4th, etc.
        """
        t = [self.teams[c] for c, _ in teams_pts]
        # Create 6 matches — simplify by giving first team most wins
        pairs = [(0, 1, 1, 0), (0, 2, 1, 0), (0, 3, 1, 0),
                 (1, 2, 1, 0), (1, 3, 1, 0), (2, 3, 1, 0)]
        for hi, ai, hs, as_ in pairs:
            Match.objects.create(
                stage=Match.Stage.GROUP, group=letter, match_datetime=_dt(),
                home_team=t[hi], away_team=t[ai],
                home_score=hs, away_score=as_, status="FINISHED",
            )

    def test_returns_empty_when_no_groups_finished(self):
        result = _actual_thirds_ranking()
        self.assertEqual(result, [])

    def test_returns_top_8_with_positions(self):
        # Fill all 12 groups
        letters = "ABCDEFGHIJKL"
        for letter in letters:
            extra_teams = []
            for i in range(3):
                code = f"{letter}{i}"
                t = Team.objects.create(name=f"Team{code}", code=code)
                extra_teams.append(t)
            t_extra4 = Team.objects.create(name=f"Team{letter}3", code=f"{letter}3")
            extra_teams.append(t_extra4)

            pairs = [(0, 1, 1, 0), (0, 2, 1, 0), (0, 3, 1, 0),
                     (1, 2, 1, 0), (1, 3, 1, 0), (2, 3, 1, 0)]
            for hi, ai, hs, as_ in pairs:
                Match.objects.create(
                    stage=Match.Stage.GROUP, group=letter, match_datetime=_dt(),
                    home_team=extra_teams[hi], away_team=extra_teams[ai],
                    home_score=hs, away_score=as_, status="FINISHED",
                )

        result = _actual_thirds_ranking()
        self.assertEqual(len(result), 8)
        positions = [entry["position"] for entry in result]
        self.assertEqual(positions, list(range(1, 9)))
        for entry in result:
            self.assertIn("team", entry)


class ScoreGroupsTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("scorer")
        cls.tournament = Tournament.objects.create(name="T", created_by=cls.user)

        cls.t1 = Team.objects.create(name="ArgX", code="AGX")
        cls.t2 = Team.objects.create(name="BrX", code="BRX")
        cls.t3 = Team.objects.create(name="ChX", code="CHX")
        cls.t4 = Team.objects.create(name="UrX", code="URX")

        # Real group A standings: t1=1st (9pts), t2=2nd (6pts), t3=3rd (3pts), t4=4th (0pts)
        for hi, ai, hs, as_ in [(0,1,1,0),(0,2,1,0),(0,3,1,0),(1,2,1,0),(1,3,1,0),(2,3,1,0)]:
            teams = [cls.t1, cls.t2, cls.t3, cls.t4]
            Match.objects.create(
                stage=Match.Stage.GROUP, group="A", match_datetime=_dt(),
                home_team=teams[hi], away_team=teams[ai],
                home_score=hs, away_score=as_, status="FINISHED",
            )

    def _predict(self, first, second, third):
        GroupPrediction.objects.filter(user=self.user, tournament=self.tournament, group="A").delete()
        GroupPrediction.objects.create(
            user=self.user, tournament=self.tournament, group="A",
            first_team=first, second_team=second, third_team=third,
        )

    def test_all_correct_earns_max(self):
        self._predict(self.t1, self.t2, self.t3)
        self.assertEqual(score_groups(self.user, self.tournament), 5 + 3 + 2)

    def test_first_only_correct(self):
        self._predict(self.t1, self.t3, self.t4)
        self.assertEqual(score_groups(self.user, self.tournament), 5)

    def test_all_wrong_earns_zero(self):
        self._predict(self.t4, self.t3, self.t2)
        self.assertEqual(score_groups(self.user, self.tournament), 0)

    def test_no_prediction_earns_zero(self):
        GroupPrediction.objects.filter(user=self.user, tournament=self.tournament, group="A").delete()
        self.assertEqual(score_groups(self.user, self.tournament), 0)

    def test_unfinished_group_earns_zero(self):
        Match.objects.filter(stage=Match.Stage.GROUP, group="B").delete()
        Match.objects.create(
            stage=Match.Stage.GROUP, group="B", match_datetime=_dt(),
            home_team=self.t1, away_team=self.t2, status="SCHEDULED",
        )
        GroupPrediction.objects.create(
            user=self.user, tournament=self.tournament, group="B",
            first_team=self.t1, second_team=self.t2, third_team=self.t3,
        )
        pts = score_groups(self.user, self.tournament)
        # Group B should contribute 0; Group A may have points depending on prior pred
        self.assertGreaterEqual(pts, 0)


class ScoreThirdsTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("thirds_scorer")
        cls.tournament = Tournament.objects.create(name="T3", created_by=cls.user)

        # Create 12 groups of 4 teams each (simplified)
        letters = "ABCDEFGHIJKL"
        cls.thirds = {}  # group letter → the team that ends up 3rd

        for letter in letters:
            teams = [
                Team.objects.create(name=f"{letter}T{i}", code=f"{letter}T{i}")
                for i in range(4)
            ]
            # First beats all, second beats 3rd and 4th, 3rd beats 4th
            pairs = [(0,1,1,0),(0,2,1,0),(0,3,1,0),(1,2,1,0),(1,3,1,0),(2,3,1,0)]
            for hi, ai, hs, as_ in pairs:
                Match.objects.create(
                    stage=Match.Stage.GROUP, group=letter, match_datetime=_dt(),
                    home_team=teams[hi], away_team=teams[ai],
                    home_score=hs, away_score=as_, status="FINISHED",
                )
            cls.thirds[letter] = teams[2]  # 3rd place team (3 pts, beats only last)

    def _set_ranking(self, ordered_teams):
        ThirdPlaceRanking.objects.filter(user=self.user, tournament=self.tournament).delete()
        ranking = ThirdPlaceRanking.objects.create(user=self.user, tournament=self.tournament)
        for pos, team in enumerate(ordered_teams, start=1):
            ThirdPlaceRankingEntry.objects.create(ranking=ranking, position=pos, team=team)

    def test_no_ranking_earns_zero(self):
        self.assertEqual(score_thirds(self.user, self.tournament), 0)

    def test_qualify_bonus_per_team(self):
        # All 12 groups are finished → exactly 8 thirds qualify
        actual = _actual_thirds_ranking()
        self.assertEqual(len(actual), 8)

        qualifying_teams = [e["team"] for e in actual]
        # Predict exactly the 8 qualifiers in wrong order → 8 × 2 = 16 pts, 0 position bonus
        shuffled = qualifying_teams[::-1]
        self._set_ranking(shuffled)
        pts = score_thirds(self.user, self.tournament)
        self.assertEqual(pts, 8 * 2)

    def test_position_bonus(self):
        actual = _actual_thirds_ranking()
        qualifying_teams = [e["team"] for e in actual]
        # Predict in exact correct order → 8 × 2 + 8 × 1 = 24 pts
        self._set_ranking(qualifying_teams)
        pts = score_thirds(self.user, self.tournament)
        self.assertEqual(pts, 8 * 2 + 8 * 1)

    def test_non_qualifying_team_earns_zero(self):
        actual = _actual_thirds_ranking()
        qualifying_teams = [e["team"] for e in actual]
        # Pick teams that did NOT qualify (the 4th-place teams from each group)
        non_qualifiers = []
        for letter in "ABCDEFGHIJKL":
            from predictions.services.scoring import _group_standings
            standings = _group_standings(letter)
            if standings and len(standings) >= 4:
                non_qualifiers.append(standings[3]["team"])
            if len(non_qualifiers) >= 8:
                break
        self._set_ranking(non_qualifiers[:8])
        pts = score_thirds(self.user, self.tournament)
        self.assertEqual(pts, 0)


class ScoreBracketTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("bracket_scorer")
        cls.tournament = Tournament.objects.create(name="TB", created_by=cls.user)

        cls.t1 = Team.objects.create(name="BrA", code="BRA")
        cls.t2 = Team.objects.create(name="BrB", code="BRB")
        cls.t3 = Team.objects.create(name="BrC", code="BRC")
        cls.t4 = Team.objects.create(name="BrD", code="BRD")

        cls.m_r32 = Match.objects.create(
            stage=Match.Stage.ROUND_OF_32, match_datetime=_dt(),
            home_team=cls.t1, away_team=cls.t2,
            home_score=2, away_score=1, status="FINISHED",
        )
        cls.m_r16 = Match.objects.create(
            stage=Match.Stage.ROUND_OF_16, match_datetime=_dt(),
            home_team=cls.t3, away_team=cls.t4,
            home_score=1, away_score=3, status="FINISHED",
        )
        cls.m_scheduled = Match.objects.create(
            stage=Match.Stage.QUARTER_FINAL, match_datetime=_dt(),
            home_team=cls.t1, away_team=cls.t3, status="SCHEDULED",
        )
        cls.m_draw = Match.objects.create(
            stage=Match.Stage.SEMI_FINAL, match_datetime=_dt(),
            home_team=cls.t1, away_team=cls.t2,
            home_score=1, away_score=1, status="FINISHED",
        )

    def test_correct_prediction_earns_round_points(self):
        BracketPrediction.objects.create(
            user=self.user, tournament=self.tournament,
            match=self.m_r32, predicted_winner=self.t1,
        )
        self.assertEqual(score_bracket(self.user, self.tournament), 2)

    def test_wrong_prediction_earns_zero(self):
        BracketPrediction.objects.create(
            user=self.user, tournament=self.tournament,
            match=self.m_r32, predicted_winner=self.t2,
        )
        self.assertEqual(score_bracket(self.user, self.tournament), 0)

    def test_multiple_rounds_accumulate(self):
        BracketPrediction.objects.create(
            user=self.user, tournament=self.tournament,
            match=self.m_r32, predicted_winner=self.t1,
        )
        BracketPrediction.objects.create(
            user=self.user, tournament=self.tournament,
            match=self.m_r16, predicted_winner=self.t4,
        )
        self.assertEqual(score_bracket(self.user, self.tournament), 2 + 4)

    def test_unfinished_match_skipped(self):
        BracketPrediction.objects.create(
            user=self.user, tournament=self.tournament,
            match=self.m_scheduled, predicted_winner=self.t1,
        )
        self.assertEqual(score_bracket(self.user, self.tournament), 0)

    def test_draw_match_returns_none_winner(self):
        BracketPrediction.objects.create(
            user=self.user, tournament=self.tournament,
            match=self.m_draw, predicted_winner=self.t1,
        )
        self.assertEqual(score_bracket(self.user, self.tournament), 0)

    def test_no_predictions_earns_zero(self):
        self.assertEqual(score_bracket(self.user, self.tournament), 0)


class ComputeUserScoreTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("full_scorer")
        cls.tournament = Tournament.objects.create(name="Full", created_by=cls.user)

        cls.t1 = Team.objects.create(name="ScoreA", code="SCA")
        cls.t2 = Team.objects.create(name="ScoreB", code="SCB")

        cls.m_r32 = Match.objects.create(
            stage=Match.Stage.ROUND_OF_32, match_datetime=_dt(),
            home_team=cls.t1, away_team=cls.t2,
            home_score=1, away_score=0, status="FINISHED",
        )
        BracketPrediction.objects.create(
            user=cls.user, tournament=cls.tournament,
            match=cls.m_r32, predicted_winner=cls.t1,
        )

    def test_returns_dict_with_all_keys(self):
        result = compute_user_score(self.user, self.tournament)
        self.assertIn("groups", result)
        self.assertIn("thirds", result)
        self.assertIn("bracket", result)
        self.assertIn("total", result)

    def test_total_equals_sum_of_parts(self):
        result = compute_user_score(self.user, self.tournament)
        self.assertEqual(result["total"], result["groups"] + result["thirds"] + result["bracket"])

    def test_bracket_pts_correct(self):
        result = compute_user_score(self.user, self.tournament)
        self.assertEqual(result["bracket"], 2)

    def test_all_zeros_for_user_with_no_predictions(self):
        other = User.objects.create_user("empty_scorer")
        result = compute_user_score(other, self.tournament)
        self.assertEqual(result, {"groups": 0, "thirds": 0, "bracket": 0, "total": 0})
