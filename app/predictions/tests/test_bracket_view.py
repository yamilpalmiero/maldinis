"""
Tests integradores para la view del bracket (/torneo/<id>/bracket/).

Verifica que cuando hay 12 GroupPredictions + ThirdPlaceRanking completo,
los 16avos se resuelven y renderizan con los equipos correctos.
Incluye test que reproduce el bug de sources vacíos (DB nueva pre-sync).
"""
from datetime import datetime, timezone

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from predictions.models import (
    GroupPrediction, Match, Team,
    ThirdPlaceRanking, ThirdPlaceRankingEntry,
)
from tournaments.models import Tournament, TournamentMember


_GROUP_LETTERS = list("ABCDEFGHIJKL")
_BRACKET_STAGES_STR = ["R32", "R16", "QF", "SF", "F"]

_R32_SOURCES = [
    ("1E", "3ABCDF"), ("1I", "3CDFGH"), ("2A", "2B"),    ("1F", "2C"),
    ("2K", "2L"),     ("1H", "2J"),     ("1D", "3BEFIJ"), ("1G", "3AEHIJ"),
    ("1C", "2F"),     ("2E", "2I"),     ("1A", "3CEFHI"), ("1L", "3EHIJK"),
    ("1J", "2H"),     ("2D", "2G"),     ("1B", "3EFGIJ"), ("1K", "3DEIJL"),
]


def _dt(month, day, hour=12):
    return datetime(2026, month, day, hour, tzinfo=timezone.utc)


class BracketViewIntegrationTest(TestCase):
    """
    Tests integradores de la view /torneo/<id>/bracket/.

    setUpTestData crea:
    - 36 equipos (3 por grupo A-L)
    - 12 GroupPredictions completas
    - ThirdPlaceRanking con 8 entries (grupos E-L, combinación válida)
    - 31 matches de eliminatoria (R32:16, R16:8, QF:4, SF:2, F:1)
      con home_source/away_source correctos basados en los IDs reales de la DB
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("bracket_view_user", password="pw")
        cls.tournament = Tournament.objects.create(name="T", created_by=cls.user)
        TournamentMember.objects.create(user=cls.user, tournament=cls.tournament)

        # 3 equipos por grupo: primero, segundo, tercero
        cls.teams = {}
        for g in _GROUP_LETTERS:
            cls.teams[g] = {
                "first":  Team.objects.create(name=f"1o_{g}", code=f"V{g}1"),
                "second": Team.objects.create(name=f"2o_{g}", code=f"V{g}2"),
                "third":  Team.objects.create(name=f"3o_{g}", code=f"V{g}3"),
            }

        # 12 GroupPredictions completas
        for g in _GROUP_LETTERS:
            GroupPrediction.objects.create(
                user=cls.user, tournament=cls.tournament, group=g,
                first_team=cls.teams[g]["first"],
                second_team=cls.teams[g]["second"],
                third_team=cls.teams[g]["third"],
            )

        # ThirdPlaceRanking: grupos E-L (combinación válida en FIFA Annex C)
        ranking = ThirdPlaceRanking.objects.create(user=cls.user, tournament=cls.tournament)
        for pos, g in enumerate(["E", "F", "G", "H", "I", "J", "K", "L"], start=1):
            ThirdPlaceRankingEntry.objects.create(
                ranking=ranking, team=cls.teams[g]["third"], position=pos,
            )

        cls.r32, cls.r16, cls.qf, cls.sf, cls.final = cls._create_bracket_tree()

    @classmethod
    def _create_bracket_tree(cls):
        """
        Crea 31 matches de eliminatoria con sources calculadas a partir de los
        IDs reales asignados por la DB (no hardcoded "W73" etc.).
        """
        r32 = [
            Match.objects.create(
                stage=Match.Stage.ROUND_OF_32,
                match_datetime=_dt(6, 21 + i // 4, 12 + i % 4),
                home_source=hs, away_source=as_,
            )
            for i, (hs, as_) in enumerate(_R32_SOURCES)
        ]

        r16 = [
            Match.objects.create(
                stage=Match.Stage.ROUND_OF_16,
                match_datetime=_dt(7, 1 + i, 15),
                home_source=f"W{r32[i * 2].id}",
                away_source=f"W{r32[i * 2 + 1].id}",
            )
            for i in range(8)
        ]

        qf = [
            Match.objects.create(
                stage=Match.Stage.QUARTER_FINAL,
                match_datetime=_dt(7, 5 + i, 15),
                home_source=f"W{r16[i * 2].id}",
                away_source=f"W{r16[i * 2 + 1].id}",
            )
            for i in range(4)
        ]

        sf = [
            Match.objects.create(
                stage=Match.Stage.SEMI_FINAL,
                match_datetime=_dt(7, 9 + i, 15),
                home_source=f"W{qf[i * 2].id}",
                away_source=f"W{qf[i * 2 + 1].id}",
            )
            for i in range(2)
        ]

        final = Match.objects.create(
            stage=Match.Stage.FINAL,
            match_datetime=_dt(7, 19, 15),
            home_source=f"W{sf[0].id}",
            away_source=f"W{sf[1].id}",
        )

        return r32, r16, qf, sf, final

    def setUp(self):
        self.client.login(username="bracket_view_user", password="pw")

    def _get(self):
        return self.client.get(reverse("bracket", args=[self.tournament.id]))

    # ── Test 1: prerequisitos ────────────────────────────────────────────────

    def test_bracket_listo_when_groups_and_thirds_complete(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        ctx = resp.context
        self.assertTrue(ctx["bracket_listo"])
        self.assertFalse(ctx["bracket_error"])

    # ── Test 2: R32 resueltos con equipos ────────────────────────────────────

    def test_r32_direct_slots_have_home_and_away_teams(self):
        """
        Los 16avos con sources "1X" vs "2Y" (slots directos, sin terceros)
        deben resolverse con home y away no-None.
        """
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        ctx = resp.context

        left_r32  = ctx["bracket_left"]["r32"]
        right_r32 = ctx["bracket_right"]["r32"]
        all_r32   = left_r32 + right_r32

        self.assertEqual(len(all_r32), 16, "Deben ser 16 matches de R32 en total")

        direct_items = [
            item for item in all_r32
            if not item["match"].away_source.startswith("3")
        ]
        self.assertGreater(len(direct_items), 0, "Debe haber al menos un slot directo en R32")

        for item in direct_items:
            self.assertIsNotNone(
                item["home"],
                f"home es None en R32 {item['match'].id} ({item['match'].home_source})",
            )
            self.assertIsNotNone(
                item["away"],
                f"away es None en R32 {item['match'].id} ({item['match'].away_source})",
            )

    # ── Test 3: HTML contiene nombres de los equipos clasificados ────────────

    def test_html_contains_classified_team_names(self):
        """El HTML del bracket debe contener los nombres de los equipos clasificados."""
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()

        # Los primeros de cada grupo deben aparecer en los 16avos via sources "1X"
        for g in _GROUP_LETTERS:
            team_name = f"1o_{g}"
            self.assertIn(
                team_name, html,
                f"El nombre del primero del grupo {g} ('{team_name}') no aparece en el bracket",
            )

        # Los segundos de algunos grupos también aparecen via sources "2X"
        self.assertIn("2o_A", html, "El segundo del grupo A ('2o_A') no aparece en el bracket")

    # ── Test 4: bug reproducido — sources vacíos → bracket_error ────────────

    def test_empty_sources_show_bracket_error_not_silent_columns(self):
        """
        Reproduce el bug: cuando home_source/away_source están vacíos
        (DB nueva pre-sync), la view debe devolver bracket_error=True en lugar
        de renderizar columnas vacías silenciosamente.
        """
        match_ids = [m.id for m in self.r32 + self.r16 + self.qf + self.sf + [self.final]]
        Match.objects.filter(id__in=match_ids).update(home_source="", away_source="")

        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        ctx = resp.context
        # Los prerequisitos siguen cumplidos
        self.assertTrue(ctx["bracket_listo"])
        # Pero el bracket no pudo resolverse
        self.assertTrue(ctx["bracket_error"], "bracket_error debe ser True cuando los sources están vacíos")
        # Los datos del bracket no se pasan al template
        self.assertIsNone(ctx["bracket_left"])
        self.assertIsNone(ctx["bracket_right"])

    # ── Test 5: mensaje de error en HTML ─────────────────────────────────────

    def test_error_message_shown_in_html_when_sources_empty(self):
        """Cuando hay bracket_error, el HTML muestra el mensaje de error en español."""
        match_ids = [m.id for m in self.r32 + self.r16 + self.qf + self.sf + [self.final]]
        Match.objects.filter(id__in=match_ids).update(home_source="", away_source="")

        resp = self._get()
        html = resp.content.decode()

        self.assertIn("Error al cargar el bracket", html)
        self.assertNotIn("Tu bracket está vacío", html)

    # ── Test 6: sin grupos ni terceros → bracket_listo=False ─────────────────

    def test_bracket_not_listo_without_predictions(self):
        """Un usuario sin predicciones ve el estado vacío, no el bracket."""
        other_user = User.objects.create_user("bracket_no_preds", password="pw")
        TournamentMember.objects.create(user=other_user, tournament=self.tournament)
        self.client.login(username="bracket_no_preds", password="pw")

        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        ctx = resp.context
        self.assertFalse(ctx["bracket_listo"])
        self.assertFalse(ctx["bracket_error"])
