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

        cls.t_arg = Team.objects.create(name="Argentina", code="ARG")
        cls.t_bra = Team.objects.create(name="Brasil",    code="BRA")
        cls.t_fra = Team.objects.create(name="Francia",   code="FRA")
        cls.t_ger = Team.objects.create(name="Alemania",  code="GER")
        cls.t_esp = Team.objects.create(name="España",    code="ESP")

        # Group A: first=ARG, second=BRA
        # Group B: first=FRA, second=GER
        # Group C: first=ESP  (second left null)
        GroupPrediction.objects.create(
            user=cls.user, tournament=cls.tournament,
            group="A", first_team=cls.t_arg, second_team=cls.t_bra,
        )
        GroupPrediction.objects.create(
            user=cls.user, tournament=cls.tournament,
            group="B", first_team=cls.t_fra, second_team=cls.t_ger,
        )
        GroupPrediction.objects.create(
            user=cls.user, tournament=cls.tournament,
            group="C", first_team=cls.t_esp,
        )

        # ── Matches ──────────────────────────────────────────────────────────
        # m_r32_a : 1A  vs 3ABCDF  → (ARG, None)
        cls.m_r32_a = Match.objects.create(
            match_datetime=_dt(21), stage=Match.Stage.ROUND_OF_32,
            home_source="1A", away_source="3ABCDF",
        )
        # m_r32_b : 2A  vs 1B     → (BRA, FRA)
        cls.m_r32_b = Match.objects.create(
            match_datetime=_dt(21, 21), stage=Match.Stage.ROUND_OF_32,
            home_source="2A", away_source="1B",
        )
        # m_r32_incon : 1A vs 1B  → (ARG, FRA) but bracket pred = GER (inconsistente)
        cls.m_r32_incon = Match.objects.create(
            match_datetime=_dt(22), stage=Match.Stage.ROUND_OF_32,
            home_source="1A", away_source="1B",
        )
        # m_missing_group : 1Z vs 2Z  → group Z no existe
        cls.m_missing_group = Match.objects.create(
            match_datetime=_dt(23), stage=Match.Stage.ROUND_OF_32,
            home_source="1Z", away_source="2Z",
        )
        # m_r16 : W(m_r32_a) vs W(m_r32_b)  → (ARG, FRA) vía bracket preds
        cls.m_r16 = Match.objects.create(
            match_datetime=_dt(26), stage=Match.Stage.ROUND_OF_16,
            home_source=f"W{cls.m_r32_a.id}", away_source=f"W{cls.m_r32_b.id}",
        )
        # m_r16_missing : W99999 vs W99998  → no hay bracket pred → (None, None)
        cls.m_r16_missing = Match.objects.create(
            match_datetime=_dt(26, 21), stage=Match.Stage.ROUND_OF_16,
            home_source="W99999", away_source="W99998",
        )
        # m_l_null : L(m_r32_a) vs 1C — loser de (ARG, None) ganado por ARG → None
        cls.m_l_null = Match.objects.create(
            match_datetime=_dt(27), stage=Match.Stage.ROUND_OF_16,
            home_source=f"L{cls.m_r32_a.id}", away_source="1C",
        )
        # m_r16_incon : L(m_r32_incon) vs 1C — winner inconsistente → None
        cls.m_r16_incon = Match.objects.create(
            match_datetime=_dt(27, 21), stage=Match.Stage.ROUND_OF_16,
            home_source=f"L{cls.m_r32_incon.id}", away_source="1C",
        )
        # m_sf : W(m_r16) vs 1C  → (ARG, ESP); user predice ESP → loser = ARG
        cls.m_sf = Match.objects.create(
            match_datetime=_dt(29), stage=Match.Stage.SEMI_FINAL,
            home_source=f"W{cls.m_r16.id}", away_source="1C",
        )
        # m_3p : L(m_sf) vs 1B  — para test de loser de SF
        cls.m_3p = Match.objects.create(
            match_datetime=_dt(30), stage=Match.Stage.THIRD_PLACE,
            home_source=f"L{cls.m_sf.id}", away_source="1B",
        )

        # ── Bracket predictions ───────────────────────────────────────────────
        BracketPrediction.objects.create(
            user=cls.user, tournament=cls.tournament,
            match=cls.m_r32_a, predicted_winner=cls.t_arg,
        )
        BracketPrediction.objects.create(
            user=cls.user, tournament=cls.tournament,
            match=cls.m_r32_b, predicted_winner=cls.t_fra,
        )
        # Inconsistente: GER no es ninguno de los equipos resueltos de m_r32_incon
        BracketPrediction.objects.create(
            user=cls.user, tournament=cls.tournament,
            match=cls.m_r32_incon, predicted_winner=cls.t_ger,
        )
        BracketPrediction.objects.create(
            user=cls.user, tournament=cls.tournament,
            match=cls.m_r16, predicted_winner=cls.t_arg,
        )
        # ESP gana la SF → loser = ARG
        BracketPrediction.objects.create(
            user=cls.user, tournament=cls.tournament,
            match=cls.m_sf, predicted_winner=cls.t_esp,
        )

    def _call(self, *matches):
        return resolve_user_bracket(self.user, self.tournament, list(matches))

    # ── Tests ─────────────────────────────────────────────────────────────────

    # 1. "1X" → first_team del grupo X
    def test_1_group_winner_resolves_first_team(self):
        result = self._call(self.m_r32_a)
        home, _ = result[self.m_r32_a.id]
        self.assertEqual(home, self.t_arg)

    # 2. "2X" → second_team del grupo X
    def test_2_group_runnerup_resolves_second_team(self):
        result = self._call(self.m_r32_b)
        home, _ = result[self.m_r32_b.id]
        self.assertEqual(home, self.t_bra)

    # 3. "3XXXXX" → siempre None
    def test_3_third_place_source_returns_none(self):
        result = self._call(self.m_r32_a)
        _, away = result[self.m_r32_a.id]
        self.assertIsNone(away)

    # 4. "WXX" → predicted_winner del BracketPrediction para match XX
    def test_4_winner_source_resolves_bracket_prediction(self):
        result = self._call(self.m_r16)
        home, away = result[self.m_r16.id]
        self.assertEqual(home, self.t_arg)  # W(m_r32_a) → ARG
        self.assertEqual(away, self.t_fra)  # W(m_r32_b) → FRA

    # 5. "LXX" → el equipo de match XX que NO es el predicted_winner
    def test_5_loser_source_resolves_non_winner(self):
        # m_sf: (ARG, ESP), user predice ESP → loser = ARG
        result = self._call(self.m_sf, self.m_3p)
        home, _ = result[self.m_3p.id]
        self.assertEqual(home, self.t_arg)

    # 6. GroupPrediction faltante → None
    def test_6_missing_group_prediction_returns_none(self):
        result = self._call(self.m_missing_group)
        home, away = result[self.m_missing_group.id]
        self.assertIsNone(home)
        self.assertIsNone(away)

    # 7. BracketPrediction faltante → None para código W
    def test_7_missing_bracket_prediction_returns_none(self):
        result = self._call(self.m_r16_missing)
        home, away = result[self.m_r16_missing.id]
        self.assertIsNone(home)
        self.assertIsNone(away)

    # 8. Cadena completa: group preds → R32 → W codes en R16 resuelve bien
    #    También verifica exactamente 3 queries (group_preds, bracket_preds, third_ranking).
    def test_8_full_chain_and_three_queries(self):
        matches = [self.m_r32_a, self.m_r32_b, self.m_r16]
        with self.assertNumQueries(3):
            result = resolve_user_bracket(self.user, self.tournament, matches)
        self.assertEqual(result[self.m_r32_a.id], (self.t_arg, None))
        self.assertEqual(result[self.m_r32_b.id], (self.t_bra, self.t_fra))
        self.assertEqual(result[self.m_r16.id],   (self.t_arg, self.t_fra))

    # 9. "LXX" cuando uno de los equipos resueltos de match XX es None → None
    def test_9_loser_source_when_one_resolved_team_is_none(self):
        # m_r32_a → (ARG, None). ARG gana. Loser = None.
        result = self._call(self.m_r32_a, self.m_l_null)
        home, _ = result[self.m_l_null.id]
        self.assertIsNone(home)

    # 10. "LXX" cuando predicted_winner no coincide con ningún equipo resuelto → None
    def test_10_loser_source_inconsistent_winner_returns_none(self):
        # m_r32_incon → (ARG, FRA). BracketPred = GER (inválido). L(m_r32_incon) = None.
        result = self._call(self.m_r32_incon, self.m_r16_incon)
        home, _ = result[self.m_r16_incon.id]
        self.assertIsNone(home)
