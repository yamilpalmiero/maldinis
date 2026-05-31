"""
Tests for resolve_user_bracket using the positional R32_SOURCES approach.

Matches are resolved purely by chronological position within each stage —
home_source/away_source DB fields are not read by the resolver.

The test setup creates:
  R32 positions 0, 1, 2 (sorted by match_datetime)
  R16 positions 0, 1

Position 0 uses R32_SOURCES[0] = ("1E", "3ABCDF") → group E first + thirds slot
Position 1 uses R32_SOURCES[1] = ("1I", "3CDFGH") → group I first (missing) + thirds slot
Position 2 uses R32_SOURCES[2] = ("2A", "2B")     → group A second vs group B second
"""
from datetime import datetime, timezone

from django.contrib.auth.models import User
from django.test import TestCase

from predictions.models import BracketPrediction, GroupPrediction, Match, Team
from predictions.services.bracket_resolver import resolve_user_bracket
from tournaments.models import Tournament


def _dt(day: int, hour: int = 18) -> datetime:
    return datetime(2026, 6, day, hour, 0, tzinfo=timezone.utc)


class ResolveUserBracketTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("tester")
        cls.tournament = Tournament.objects.create(name="Test", created_by=cls.user)

        cls.t_esp = Team.objects.create(name="España",    code="ESP")  # group E first
        cls.t_arg = Team.objects.create(name="Argentina", code="ARG")  # group A first
        cls.t_bra = Team.objects.create(name="Brasil",    code="BRA")  # group A second
        cls.t_fra = Team.objects.create(name="Francia",   code="FRA")  # group B first
        cls.t_ger = Team.objects.create(name="Alemania",  code="GER")  # group B second

        # Groups referenced by R32_SOURCES[0..2]
        GroupPrediction.objects.create(
            user=cls.user, tournament=cls.tournament,
            group="E", first_team=cls.t_esp,
        )
        GroupPrediction.objects.create(
            user=cls.user, tournament=cls.tournament,
            group="A", first_team=cls.t_arg, second_team=cls.t_bra,
        )
        GroupPrediction.objects.create(
            user=cls.user, tournament=cls.tournament,
            group="B", first_team=cls.t_fra, second_team=cls.t_ger,
        )

        # R32 matches: chronological order determines positional index
        cls.m_r32_0 = Match.objects.create(
            match_datetime=_dt(21),     stage=Match.Stage.ROUND_OF_32,
        )
        cls.m_r32_1 = Match.objects.create(
            match_datetime=_dt(21, 21), stage=Match.Stage.ROUND_OF_32,
        )
        cls.m_r32_2 = Match.objects.create(
            match_datetime=_dt(22),     stage=Match.Stage.ROUND_OF_32,
        )

        # R16 matches
        cls.m_r16_0 = Match.objects.create(
            match_datetime=_dt(26),     stage=Match.Stage.ROUND_OF_16,
        )
        cls.m_r16_1 = Match.objects.create(
            match_datetime=_dt(26, 21), stage=Match.Stage.ROUND_OF_16,
        )

        # Bracket predictions
        BracketPrediction.objects.create(
            user=cls.user, tournament=cls.tournament,
            match=cls.m_r32_0, predicted_winner=cls.t_esp,
        )
        BracketPrediction.objects.create(
            user=cls.user, tournament=cls.tournament,
            match=cls.m_r32_2, predicted_winner=cls.t_bra,
        )

    def _all(self):
        return [self.m_r32_0, self.m_r32_1, self.m_r32_2, self.m_r16_0, self.m_r16_1]

    # 1. R32 pos 0 home: R32_SOURCES[0] = "1E" → group E first_team
    def test_1_r32_home_group_winner(self):
        result = resolve_user_bracket(self.user, self.tournament, self._all())
        home, _ = result[self.m_r32_0.id]
        self.assertEqual(home, self.t_esp)

    # 2. R32 pos 2 home: R32_SOURCES[2] = "2A" → group A second_team
    def test_2_r32_home_group_runnerup(self):
        result = resolve_user_bracket(self.user, self.tournament, self._all())
        home, _ = result[self.m_r32_2.id]
        self.assertEqual(home, self.t_bra)

    # 3. R32 pos 2 away: R32_SOURCES[2] = "2B" → group B second_team
    def test_3_r32_away_group_runnerup(self):
        result = resolve_user_bracket(self.user, self.tournament, self._all())
        _, away = result[self.m_r32_2.id]
        self.assertEqual(away, self.t_ger)

    # 4. R32 pos 0 away: "3ABCDF" → None without ThirdPlaceRanking
    def test_4_r32_third_slot_none_without_ranking(self):
        result = resolve_user_bracket(self.user, self.tournament, self._all())
        _, away = result[self.m_r32_0.id]
        self.assertIsNone(away)

    # 5. R16 pos 1 home: winner of r32[2] → BRA (bracket prediction)
    def test_5_r16_home_resolves_r32_winner(self):
        result = resolve_user_bracket(self.user, self.tournament, self._all())
        home, _ = result[self.m_r16_1.id]
        self.assertEqual(home, self.t_bra)

    # 6. R16 pos 0 home: winner of r32[0] → ESP (bracket prediction)
    def test_6_r16_home_resolves_r32_winner_chain(self):
        result = resolve_user_bracket(self.user, self.tournament, self._all())
        home, _ = result[self.m_r16_0.id]
        self.assertEqual(home, self.t_esp)

    # 7. Missing group prediction → None (group I has no prediction)
    def test_7_missing_group_prediction_returns_none(self):
        result = resolve_user_bracket(self.user, self.tournament, self._all())
        home, _ = result[self.m_r32_1.id]
        self.assertIsNone(home)

    # 8. Missing bracket prediction → None in downstream R16
    def test_8_missing_bracket_pred_gives_none_in_r16(self):
        # r16[0] away = winner of r32[1] — no bracket pred for m_r32_1
        result = resolve_user_bracket(self.user, self.tournament, self._all())
        _, away = result[self.m_r16_0.id]
        self.assertIsNone(away)

    # 9. Exactly 3 DB queries
    def test_9_exactly_three_queries(self):
        with self.assertNumQueries(3):
            resolve_user_bracket(self.user, self.tournament, self._all())

    # 10. Full chain: r32[2] resolved teams propagate correctly to r16[1]
    def test_10_full_chain_r32_to_r16(self):
        result = resolve_user_bracket(self.user, self.tournament, self._all())
        self.assertEqual(result[self.m_r32_2.id], (self.t_bra, self.t_ger))
        # r16[1] home = winner(r32[2]) = BRA; away = winner(r32[3]) = None (doesn't exist)
        self.assertEqual(result[self.m_r16_1.id], (self.t_bra, None))
