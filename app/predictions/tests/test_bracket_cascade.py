"""
Tests para la cascada de borrado al cambiar/limpiar el ganador en el bracket personal
(fase 14e paso 4).
"""
import json
from datetime import datetime, timezone

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from predictions.models import BracketPrediction, GroupPrediction, Match, Team
from tournaments.models import Tournament, TournamentMember


def _dt(day: int, hour: int = 18) -> datetime:
    return datetime(2026, 6, day, hour, 0, tzinfo=timezone.utc)


class BracketPredictCascadeTest(TestCase):
    """
    Verifica que bracket_predict calcula la cascada de borrado correctamente:
    - Cambiar ganador en R32 → predicción de R16 que usaba ese equipo queda borrada.
    - Limpiar ganador en R32 → idem.
    - Predicciones independientes no se tocan.
    - Re-enviar el mismo ganador → deleted vacío, sin cambios.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("cascade_tester", password="pw")
        cls.tournament = Tournament.objects.create(name="T", created_by=cls.user)
        TournamentMember.objects.create(user=cls.user, tournament=cls.tournament)

        cls.t_arg = Team.objects.create(name="Argentina", code="ARG")
        cls.t_bra = Team.objects.create(name="Brasil",    code="BRA")
        cls.t_esp = Team.objects.create(name="España",    code="ESP")
        cls.t_fra = Team.objects.create(name="Francia",   code="FRA")

        # Group predictions para que resolve_user_bracket pueda validar equipos
        GroupPrediction.objects.create(
            user=cls.user, tournament=cls.tournament,
            group="A", first_team=cls.t_arg, second_team=cls.t_bra,
        )
        GroupPrediction.objects.create(
            user=cls.user, tournament=cls.tournament,
            group="B", first_team=cls.t_bra, second_team=cls.t_arg,
        )
        GroupPrediction.objects.create(
            user=cls.user, tournament=cls.tournament,
            group="C", first_team=cls.t_esp,
        )

        # m_r32: 1A vs 1B → (ARG, BRA)
        cls.m_r32 = Match.objects.create(
            match_datetime=_dt(21), stage=Match.Stage.ROUND_OF_32,
            home_source="1A", away_source="1B",
        )
        # m_r16: W(m_r32) vs 1C → (ARG, ESP) mientras ARG gana R32
        cls.m_r16 = Match.objects.create(
            match_datetime=_dt(26), stage=Match.Stage.ROUND_OF_16,
            home_source=f"W{cls.m_r32.id}", away_source="1C",
        )
        # m_r16_other: sin dependencia sobre m_r32
        cls.m_r16_other = Match.objects.create(
            match_datetime=_dt(26, 21), stage=Match.Stage.ROUND_OF_16,
            home_source="1A", away_source="1B",
        )

    def setUp(self):
        # Recrear predicciones frescas antes de cada test
        BracketPrediction.objects.filter(user=self.user, tournament=self.tournament).delete()
        BracketPrediction.objects.create(
            user=self.user, tournament=self.tournament,
            match=self.m_r32, predicted_winner=self.t_arg,
        )
        BracketPrediction.objects.create(
            user=self.user, tournament=self.tournament,
            match=self.m_r16, predicted_winner=self.t_arg,
        )
        BracketPrediction.objects.create(
            user=self.user, tournament=self.tournament,
            match=self.m_r16_other, predicted_winner=self.t_bra,
        )
        self.client.login(username="cascade_tester", password="pw")

    def _post(self, match_id, winner_team_id):
        return self.client.post(
            reverse("bracket_predict", args=[self.tournament.id]),
            data=json.dumps({"match_id": match_id, "winner_team_id": winner_team_id}),
            content_type="application/json",
        )

    def test_change_winner_cascades_downstream(self):
        """Cambiar R32 de ARG→BRA borra la predicción de R16 que avanzaba a ARG."""
        resp = self._post(self.m_r32.id, self.t_bra.id)
        data = json.loads(resp.content)

        self.assertTrue(data["ok"])
        self.assertEqual(data["saved"]["winner_team_id"], self.t_bra.id)
        self.assertIn(self.m_r16.id, data["deleted"])
        self.assertNotIn(self.m_r16_other.id, data["deleted"])

        self.assertEqual(
            BracketPrediction.objects.get(match=self.m_r32, user=self.user).predicted_winner_id,
            self.t_bra.id,
        )
        self.assertFalse(
            BracketPrediction.objects.filter(match=self.m_r16, user=self.user).exists()
        )
        self.assertTrue(
            BracketPrediction.objects.filter(match=self.m_r16_other, user=self.user).exists()
        )

    def test_clear_winner_cascades_downstream(self):
        """Limpiar R32 (winner=null) borra la predicción de R16."""
        resp = self._post(self.m_r32.id, None)
        data = json.loads(resp.content)

        self.assertTrue(data["ok"])
        self.assertIsNone(data["saved"])
        self.assertIn(self.m_r16.id, data["deleted"])

        self.assertFalse(
            BracketPrediction.objects.filter(match=self.m_r32, user=self.user).exists()
        )
        self.assertFalse(
            BracketPrediction.objects.filter(match=self.m_r16, user=self.user).exists()
        )
        self.assertTrue(
            BracketPrediction.objects.filter(match=self.m_r16_other, user=self.user).exists()
        )

    def test_no_cascade_when_winner_unchanged(self):
        """Re-seleccionar el mismo ganador no genera cascada ni modifica predicciones."""
        resp = self._post(self.m_r32.id, self.t_arg.id)
        data = json.loads(resp.content)

        self.assertTrue(data["ok"])
        self.assertEqual(data["deleted"], [])
        self.assertTrue(
            BracketPrediction.objects.filter(
                match=self.m_r16, user=self.user, predicted_winner=self.t_arg
            ).exists()
        )

    def test_independent_prediction_never_deleted(self):
        """Predicción de partido sin dependencia en m_r32 no se borra en ningún caso."""
        self._post(self.m_r32.id, self.t_bra.id)
        self.assertTrue(
            BracketPrediction.objects.filter(match=self.m_r16_other, user=self.user).exists()
        )
