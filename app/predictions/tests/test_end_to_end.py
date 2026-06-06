"""
Suite end-to-end para Maldinis.

8 flujos críticos usando TestClient de Django + unittest.mock.
Sin dependencias externas. Cada clase es independiente.

Los fixtures 'teams' y 'matches' cargan 48 equipos + 72 partidos de
fase de grupos (6 por grupo, grupos A–L), tal como en producción.
"""
import json
from datetime import datetime, timezone
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

import predictions.api as api_module
from predictions.models import (
    BracketPrediction,
    GroupPrediction,
    Match,
    Team,
    ThirdPlaceRanking,
    ThirdPlaceRankingEntry,
)
from predictions.services.scoring import compute_user_score
from predictions.utils import get_tournament_deadline
from tournaments.models import Tournament, TournamentMember


# ── Datos de grupos según fixtures/teams.json + fixtures/matches.json ─────────
# Cada grupo tiene 4 equipos; predicción: (1º pk, 2º pk, 3º pk)

GROUP_PRED = {
    "A": (1,  13, 24),   # México, Corea del Sur, Sudáfrica
    "B": (3,  16, 37),   # Canadá, Catar, Suiza
    "C": (7,  18, 38),   # Brasil, Marruecos, Escocia
    "D": (2,  10, 15),   # Estados Unidos, Paraguay, Australia
    "E": (8,  25, 33),   # Ecuador, Costa de Marfil, Alemania
    "F": (4,  19, 32),   # Japón, Túnez, Países Bajos
    "G": (5,  20, 34),   # Nueva Zelanda, Egipto, Bélgica
    "H": (9,  17, 23),   # Uruguay, Arabia Saudita, Cabo Verde
    "I": (26, 29, 31),   # Senegal, Francia, Noruega
    "J": (6,  14, 21),   # Argentina, Jordania, Argelia
    "K": (11, 12, 30),   # Colombia, Uzbekistán, Portugal
    "L": (22, 27, 28),   # Ghana, Inglaterra, Croacia
}

# 8 terceros de grupos A–H → combinación válida en FIFA Annex C
# frozenset(ABCDEFGH): {"74":"C","77":"F","79":"H","80":"E","81":"B","82":"A","85":"G","87":"D"}
THIRDS_ORDER = [GROUP_PRED[g][2] for g in "ABCDEFGH"]
# [24, 37, 38, 15, 33, 32, 34, 23]


# ── Helpers compartidos ───────────────────────────────────────────────────────

def _dt(month: int, day: int, hour: int = 12) -> datetime:
    return datetime(2026, month, day, hour, 0, tzinfo=timezone.utc)


def _create_knockout_matches() -> list[Match]:
    """31 partidos de eliminatoria en orden cronológico (alineado a R32_SOURCES)."""
    configs = [
        (Match.Stage.ROUND_OF_32,   [(7, d) for d in range(1, 17)]),
        (Match.Stage.ROUND_OF_16,   [(7, d) for d in range(17, 25)]),
        (Match.Stage.QUARTER_FINAL, [(7, d) for d in range(25, 29)]),
        (Match.Stage.SEMI_FINAL,    [(7, 29), (7, 30)]),
        (Match.Stage.FINAL,         [(8, 1)]),
    ]
    matches = []
    for stage, month_days in configs:
        for month, day in month_days:
            matches.append(Match.objects.create(
                stage=stage,
                match_datetime=_dt(month, day),
            ))
    return matches


def _make_group_predictions(user, tournament) -> None:
    for g, (f, s, t) in GROUP_PRED.items():
        GroupPrediction.objects.create(
            user=user, tournament=tournament, group=g,
            first_team_id=f, second_team_id=s, third_team_id=t,
        )


def _make_thirds_ranking(user, tournament) -> ThirdPlaceRanking:
    ranking = ThirdPlaceRanking.objects.create(user=user, tournament=tournament)
    for pos, pk in enumerate(THIRDS_ORDER, start=1):
        ThirdPlaceRankingEntry.objects.create(ranking=ranking, team_id=pk, position=pos)
    return ranking


def _post_json(client, url, data):
    return client.post(url, json.dumps(data), content_type="application/json")


# ─────────────────────────────────────────────────────────────────────────────
# 1. FLUJO REGISTRO + LOGIN + CREAR TORNEO
# ─────────────────────────────────────────────────────────────────────────────

class RegistroLoginTorneoTest(TestCase):

    def setUp(self):
        get_tournament_deadline.cache_clear()

    def test_registro_crea_usuario_y_redirige(self):
        resp = self.client.post(reverse("registro"), {
            "username":  "jugador1",
            "password1": "testpass123",
            "password2": "testpass123",
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(User.objects.filter(username="jugador1").exists())

    def test_crear_torneo_y_aparece_en_mis_torneos(self):
        user = User.objects.create_user("jugador2", password="pw")
        self.client.login(username="jugador2", password="pw")

        resp = self.client.post(reverse("crear_torneo"), {"name": "El Clasico"}, follow=True)
        self.assertRedirects(resp, reverse("mis_torneos"))

        tournament = Tournament.objects.get(name="El Clasico")
        self.assertEqual(tournament.created_by, user)
        self.assertTrue(TournamentMember.objects.filter(tournament=tournament, user=user).exists())

        resp = self.client.get(reverse("mis_torneos"))
        self.assertContains(resp, "El Clasico")

    def test_segundo_usuario_se_une_con_invite_code(self):
        owner = User.objects.create_user("owner", password="pw")
        self.client.login(username="owner", password="pw")
        self.client.post(reverse("crear_torneo"), {"name": "Torneo Amigos"})

        tournament = Tournament.objects.get(name="Torneo Amigos")
        invite_code = tournament.invite_code

        # Nuevo usuario se une
        joiner = User.objects.create_user("joiner", password="pw")
        self.client.login(username="joiner", password="pw")
        resp = self.client.post(reverse("unirse_torneo"), {"invite_code": invite_code}, follow=True)
        self.assertRedirects(resp, reverse("mis_torneos"))

        # Ambos son miembros
        self.assertEqual(TournamentMember.objects.filter(tournament=tournament).count(), 2)

        # El joiner ve el torneo en su lista
        resp = self.client.get(reverse("mis_torneos"))
        self.assertContains(resp, "Torneo Amigos")

    def test_codigo_invalido_muestra_error(self):
        User.objects.create_user("u3", password="pw")
        self.client.login(username="u3", password="pw")
        resp = self.client.post(reverse("unirse_torneo"), {"invite_code": "XXXXXXXX"}, follow=True)
        self.assertContains(resp, "inválido")

    def test_nombre_duplicado_rechazado(self):
        user = User.objects.create_user("u4", password="pw")
        self.client.login(username="u4", password="pw")
        self.client.post(reverse("crear_torneo"), {"name": "Duplicado"})
        resp = self.client.post(reverse("crear_torneo"), {"name": "Duplicado"}, follow=True)
        self.assertContains(resp, "Duplicado")  # error de nombre duplicado
        self.assertEqual(Tournament.objects.filter(name="Duplicado", created_by=user).count(), 1)


# ─────────────────────────────────────────────────────────────────────────────
# 2. FLUJO PREDICCIONES DE GRUPOS COMPLETO
# ─────────────────────────────────────────────────────────────────────────────

class GrupoPrediccionesTest(TestCase):
    fixtures = ["teams", "matches"]

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("grupos_user", password="pw")
        cls.t = Tournament.objects.create(name="T", created_by=cls.user)
        TournamentMember.objects.create(user=cls.user, tournament=cls.t)

    def setUp(self):
        get_tournament_deadline.cache_clear()
        self.client.login(username="grupos_user", password="pw")

    def _save_group(self, letter, first, second, third):
        return _post_json(self.client,
            reverse("save_group_prediction", args=[self.t.id, letter]),
            {"first": first, "second": second, "third": third},
        )

    def test_guardar_doce_grupos_retorna_ok(self):
        for g, (f, s, t) in GROUP_PRED.items():
            resp = self._save_group(g, f, s, t)
            data = json.loads(resp.content)
            self.assertTrue(data["ok"], f"Grupo {g} falló: {data}")

        self.assertEqual(
            GroupPrediction.objects.filter(user=self.user, tournament=self.t).count(),
            12,
        )

    def test_prediccion_persiste_tras_recargar(self):
        f, s, t = GROUP_PRED["A"]
        self._save_group("A", f, s, t)

        gp = GroupPrediction.objects.get(user=self.user, tournament=self.t, group="A")
        self.assertEqual(gp.first_team_id, f)
        self.assertEqual(gp.second_team_id, s)
        self.assertEqual(gp.third_team_id, t)

    def test_editar_prediccion_actualiza_correctamente(self):
        f, s, t = GROUP_PRED["A"]
        self._save_group("A", f, s, t)

        # Intercambiar 1º y 2º
        resp = self._save_group("A", s, f, t)
        self.assertTrue(json.loads(resp.content)["ok"])

        gp = GroupPrediction.objects.get(user=self.user, tournament=self.t, group="A")
        self.assertEqual(gp.first_team_id, s)
        self.assertEqual(gp.second_team_id, f)

    def test_equipo_fuera_del_grupo_es_rechazado(self):
        # Grupo A: equipos 1,13,24,45. El pk 3 (Canadá) es del Grupo B.
        f, s, t = GROUP_PRED["A"]
        resp = self._save_group("A", 3, s, t)  # 3 no pertenece al Grupo A
        data = json.loads(resp.content)
        self.assertTrue(data["ok"])
        # El equipo inválido se descarta; first_id queda en None
        gp = GroupPrediction.objects.get(user=self.user, tournament=self.t, group="A")
        self.assertIsNone(gp.first_team_id)  # primer slot vacío

    def test_equipos_duplicados_rechazados(self):
        f, s, _ = GROUP_PRED["A"]
        resp = self._save_group("A", f, f, s)  # f repetido
        self.assertEqual(resp.status_code, 400)

    def test_mis_predicciones_renderiza_sin_error(self):
        resp = self.client.get(reverse("mis_predicciones", args=[self.t.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Grupo A")


# ─────────────────────────────────────────────────────────────────────────────
# 3. FLUJO PREDICCIONES DE TERCEROS COMPLETO
# ─────────────────────────────────────────────────────────────────────────────

class TercerosPrediccionesTest(TestCase):
    fixtures = ["teams", "matches"]

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("terceros_user", password="pw")
        cls.t = Tournament.objects.create(name="T", created_by=cls.user)
        TournamentMember.objects.create(user=cls.user, tournament=cls.t)
        _make_group_predictions(cls.user, cls.t)

    def setUp(self):
        get_tournament_deadline.cache_clear()
        self.client.login(username="terceros_user", password="pw")

    def _save_terceros(self, order):
        return _post_json(self.client,
            reverse("save_terceros", args=[self.t.id]),
            {"order": ",".join(str(pk) for pk in order)},
        )

    def test_guardar_ocho_terceros_retorna_ok(self):
        resp = self._save_terceros(THIRDS_ORDER)
        self.assertTrue(json.loads(resp.content)["ok"])

        entries = list(
            ThirdPlaceRankingEntry.objects
            .filter(ranking__user=self.user, ranking__tournament=self.t)
            .order_by("position")
            .values_list("team_id", "position")
        )
        self.assertEqual(len(entries), 8)
        for i, (pk, pos) in enumerate(entries):
            self.assertEqual(pos, i + 1)
            self.assertEqual(pk, THIRDS_ORDER[i])

    def test_reordenar_terceros_actualiza_posiciones(self):
        self._save_terceros(THIRDS_ORDER)

        # Invertir el orden
        reversed_order = list(reversed(THIRDS_ORDER))
        resp = self._save_terceros(reversed_order)
        self.assertTrue(json.loads(resp.content)["ok"])

        entries = list(
            ThirdPlaceRankingEntry.objects
            .filter(ranking__user=self.user, ranking__tournament=self.t)
            .order_by("position")
            .values_list("team_id", flat=True)
        )
        self.assertEqual(entries, reversed_order)

    def test_menos_de_8_terceros_retorna_400(self):
        resp = self._save_terceros(THIRDS_ORDER[:5])
        self.assertEqual(resp.status_code, 400)

    def test_terceros_de_otro_grupo_filtrados(self):
        # Incluir un pk que no es third de ningún grupo → se filtra
        bogus_pk = 999
        order_con_bogus = [bogus_pk] + list(THIRDS_ORDER[:7])
        resp = self._save_terceros(order_con_bogus)
        # Solo 7 válidos → < 8 → 400
        self.assertEqual(resp.status_code, 400)


# ─────────────────────────────────────────────────────────────────────────────
# 4. FLUJO BRACKET COMPLETO
# ─────────────────────────────────────────────────────────────────────────────

class BracketCompletoTest(TestCase):
    fixtures = ["teams", "matches"]

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("bracket_user", password="pw")
        cls.t = Tournament.objects.create(name="T", created_by=cls.user)
        TournamentMember.objects.create(user=cls.user, tournament=cls.t)

        all_matches = _create_knockout_matches()
        cls.r32 = [m for m in all_matches if m.stage == Match.Stage.ROUND_OF_32]
        cls.r16 = [m for m in all_matches if m.stage == Match.Stage.ROUND_OF_16]
        cls.sf  = [m for m in all_matches if m.stage == Match.Stage.SEMI_FINAL]
        cls.final_m = next(m for m in all_matches if m.stage == Match.Stage.FINAL)

        _make_group_predictions(cls.user, cls.t)
        _make_thirds_ranking(cls.user, cls.t)

    def setUp(self):
        get_tournament_deadline.cache_clear()
        self.client.login(username="bracket_user", password="pw")

    def _predict(self, match_id, winner_id):
        return _post_json(self.client,
            reverse("bracket_predict", args=[self.t.id]),
            {"match_id": match_id, "winner_team_id": winner_id},
        )

    # ── 4a. Vista GET: bracket se resuelve sin error ──────────────────────────

    def test_bracket_listo_y_sin_error(self):
        resp = self.client.get(reverse("bracket", args=[self.t.id]))
        self.assertEqual(resp.status_code, 200)
        ctx = resp.context
        self.assertTrue(ctx["bracket_listo"])
        self.assertFalse(ctx["bracket_error"])
        self.assertIsNotNone(ctx["bracket_left"])
        self.assertIsNotNone(ctx["bracket_right"])

    def test_r32_tiene_16_partidos(self):
        resp = self.client.get(reverse("bracket", args=[self.t.id]))
        ctx = resp.context
        total_r32 = len(ctx["bracket_left"]["r32"]) + len(ctx["bracket_right"]["r32"])
        self.assertEqual(total_r32, 16)

    def test_r32_posicion_2_resuelve_korea_vs_qatar(self):
        """R32_SOURCES[2] = ('2A', '2B') → Korea(13) vs Qatar(16)."""
        resp = self.client.get(reverse("bracket", args=[self.t.id]))
        ctx = resp.context
        item = ctx["bracket_left"]["r32"][2]  # posición 2 queda en el lado izquierdo
        self.assertEqual(item["home"].pk, 13)  # 2º Grupo A = Corea del Sur
        self.assertEqual(item["away"].pk, 16)  # 2º Grupo B = Catar

    def test_r32_posicion_10_resuelve_mexico_vs_tercer_h(self):
        """R32_SOURCES[10] = ('1A', '3CEFHI') → Mexico(1) vs CaboVerde(23)."""
        resp = self.client.get(reverse("bracket", args=[self.t.id]))
        ctx = resp.context
        # pos 10 está en el lado derecho (posiciones 8-15 → right[0..7])
        item = ctx["bracket_right"]["r32"][2]  # pos 10 = right[2]
        self.assertEqual(item["home"].pk, 1)   # 1º Grupo A = México
        self.assertEqual(item["away"].pk, 23)  # 3º Grupo H = Cabo Verde (combo ABCDEFGH)

    # ── 4b. Guardar ganador de R32 ────────────────────────────────────────────

    def test_guardar_ganador_r32_retorna_ok(self):
        """Korea(13) gana R32 pos 2 (Korea vs Qatar)."""
        resp = self._predict(self.r32[2].id, 13)
        data = json.loads(resp.content)
        self.assertTrue(data["ok"])
        self.assertEqual(data["saved"]["winner_team_id"], 13)

        pred = BracketPrediction.objects.get(
            user=self.user, tournament=self.t, match=self.r32[2]
        )
        self.assertEqual(pred.predicted_winner_id, 13)

    def test_equipo_no_en_partido_rechazado(self):
        """Argentina(6) no juega en R32[2] (Korea vs Qatar) → error."""
        resp = self._predict(self.r32[2].id, 6)
        data = json.loads(resp.content)
        self.assertFalse(data["ok"])

    # ── 4c. Cascada de borrado ────────────────────────────────────────────────

    def test_cambiar_ganador_r32_borra_prediccion_r16_aguas_abajo(self):
        """
        Predecir Korea(13) en R32[2] y en R16[1].
        Cambiar R32[2] a Qatar(16).
        → R16[1] queda borrada (cascada).
        """
        # Korea gana R32[2]
        self._predict(self.r32[2].id, 13)

        # Korea también gana R16[1] (home = winner R32[2] = Korea)
        resp = self._predict(self.r16[1].id, 13)
        self.assertTrue(json.loads(resp.content)["ok"])

        # Cambiar R32[2] a Qatar(16)
        resp = self._predict(self.r32[2].id, 16)
        data = json.loads(resp.content)
        self.assertTrue(data["ok"])
        self.assertIn(self.r16[1].id, data["deleted"])

        # R16[1] ya no existe en DB
        self.assertFalse(BracketPrediction.objects.filter(
            user=self.user, tournament=self.t, match=self.r16[1]
        ).exists())

    def test_prediccion_independiente_no_se_borra_en_cascada(self):
        """R16[0] (depende de R32[0] y R32[1]) no se toca al cambiar R32[2]."""
        # Ecuador(8) gana R32[0] y R16[0]
        self._predict(self.r32[0].id, 8)   # Ecuador vs Scotland → Ecuador wins
        resp = self._predict(self.r16[0].id, 8)
        self.assertTrue(json.loads(resp.content)["ok"])

        # Korea gana R32[2]
        self._predict(self.r32[2].id, 13)
        # Cambiar R32[2] a Qatar → R16[0] NO debe borrarse
        resp = self._predict(self.r32[2].id, 16)
        data = json.loads(resp.content)
        self.assertNotIn(self.r16[0].id, data["deleted"])
        self.assertTrue(BracketPrediction.objects.filter(
            user=self.user, tournament=self.t, match=self.r16[0]
        ).exists())

    def test_limpiar_ganador_r32_borra_cascada(self):
        """Limpiar R32[2] (winner=null) también dispara la cascada."""
        self._predict(self.r32[2].id, 13)
        self._predict(self.r16[1].id, 13)

        resp = _post_json(self.client,
            reverse("bracket_predict", args=[self.t.id]),
            {"match_id": self.r32[2].id, "winner_team_id": None},
        )
        data = json.loads(resp.content)
        self.assertTrue(data["ok"])
        self.assertIn(self.r16[1].id, data["deleted"])

    # ── 4d. Campeón ───────────────────────────────────────────────────────────

    def test_campeon_aparece_cuando_hay_prediccion_final(self):
        """Si hay BracketPrediction para la Final, champion se muestra en el contexto."""
        BracketPrediction.objects.create(
            user=self.user, tournament=self.t,
            match=self.final_m, predicted_winner_id=1,  # México
        )
        resp = self.client.get(reverse("bracket", args=[self.t.id]))
        ctx = resp.context
        self.assertIsNotNone(ctx.get("champion"))
        self.assertEqual(ctx["champion"].pk, 1)


# ─────────────────────────────────────────────────────────────────────────────
# 5. FLUJO RANKING + SCORING
# ─────────────────────────────────────────────────────────────────────────────

class ScoringRankingTest(TestCase):
    """
    Crea datos desde cero (sin fixtures) para tener control total de los resultados.
    """

    @classmethod
    def setUpTestData(cls):
        # Equipos del Grupo A (creados desde cero)
        cls.mexico       = Team.objects.create(name="México",      code="MX2")
        cls.korea        = Team.objects.create(name="Corea",       code="KO2")
        cls.sudafrica    = Team.objects.create(name="Sudáfrica",   code="SA2")
        cls.chequia      = Team.objects.create(name="Chequia",     code="CZ2")

        # 6 partidos del Grupo A, todos FINISHED
        def m(home, away, hs, as_):
            return Match.objects.create(
                stage=Match.Stage.GROUP, group="A",
                match_datetime=_dt(6, 15),
                home_team=home, away_team=away,
                home_score=hs, away_score=as_, status="FINISHED",
            )
        m(cls.mexico,    cls.korea,     2, 0)
        m(cls.mexico,    cls.sudafrica, 1, 0)
        m(cls.mexico,    cls.chequia,   1, 0)
        m(cls.korea,     cls.sudafrica, 1, 0)
        m(cls.korea,     cls.chequia,   1, 0)
        m(cls.sudafrica, cls.chequia,   1, 0)
        # Standings: México(9), Corea(6), Sudáfrica(3), Chequia(0)

        # 1 partido de eliminatoria FINISHED (R32)
        cls.r32_match = Match.objects.create(
            stage=Match.Stage.ROUND_OF_32,
            match_datetime=_dt(7, 5),
            home_team=cls.mexico, away_team=cls.korea,
            home_score=2, away_score=1, status="FINISHED",
        )

        cls.user_a = User.objects.create_user("scorer_a", password="pw")
        cls.user_b = User.objects.create_user("scorer_b", password="pw")
        cls.user_c = User.objects.create_user("scorer_c", password="pw")

        cls.t = Tournament.objects.create(name="T", created_by=cls.user_a)
        for u in [cls.user_a, cls.user_b, cls.user_c]:
            TournamentMember.objects.create(user=u, tournament=cls.t)

        # user_a: predicción perfecta Grupo A + R32
        GroupPrediction.objects.create(
            user=cls.user_a, tournament=cls.t, group="A",
            first_team=cls.mexico, second_team=cls.korea, third_team=cls.sudafrica,
        )
        BracketPrediction.objects.create(
            user=cls.user_a, tournament=cls.t,
            match=cls.r32_match, predicted_winner=cls.mexico,
        )

        # user_b: predicción parcial (acierta 1º pero no 2º ni 3º; acierta R32)
        GroupPrediction.objects.create(
            user=cls.user_b, tournament=cls.t, group="A",
            first_team=cls.mexico, second_team=cls.sudafrica, third_team=cls.korea,
        )
        BracketPrediction.objects.create(
            user=cls.user_b, tournament=cls.t,
            match=cls.r32_match, predicted_winner=cls.mexico,
        )

        # user_c: todo mal
        GroupPrediction.objects.create(
            user=cls.user_c, tournament=cls.t, group="A",
            first_team=cls.chequia, second_team=cls.sudafrica, third_team=cls.korea,
        )
        BracketPrediction.objects.create(
            user=cls.user_c, tournament=cls.t,
            match=cls.r32_match, predicted_winner=cls.korea,  # perdedor
        )

    def setUp(self):
        get_tournament_deadline.cache_clear()

    # ── Score groups ─────────────────────────────────────────────────────────

    def test_score_grupos_perfecto_da_10_pts(self):
        score = compute_user_score(self.user_a, self.t)
        self.assertEqual(score["groups"], 10)  # 5+3+2

    def test_score_grupos_parcial(self):
        # user_b acierta 1º (5pts) pero 2º y 3º mal → 5 pts
        score = compute_user_score(self.user_b, self.t)
        self.assertEqual(score["groups"], 5)

    def test_score_grupos_todo_mal_da_0(self):
        score = compute_user_score(self.user_c, self.t)
        self.assertEqual(score["groups"], 0)

    # ── Score bracket ─────────────────────────────────────────────────────────

    def test_score_bracket_ganador_correcto(self):
        # user_a predijo México y México ganó → 2 pts (R32)
        score = compute_user_score(self.user_a, self.t)
        self.assertEqual(score["bracket"], 2)

    def test_score_bracket_ganador_incorrecto_da_0(self):
        score = compute_user_score(self.user_c, self.t)
        self.assertEqual(score["bracket"], 0)

    # ── Total ─────────────────────────────────────────────────────────────────

    def test_total_suma_grupos_y_bracket(self):
        score = compute_user_score(self.user_a, self.t)
        self.assertEqual(score["total"], score["groups"] + score["thirds"] + score["bracket"])

    # ── Ranking page ──────────────────────────────────────────────────────────

    def test_ranking_muestra_usuarios_en_orden_descendente(self):
        self.client.login(username="scorer_a", password="pw")
        resp = self.client.get(reverse("ranking", args=[self.t.id]))
        self.assertEqual(resp.status_code, 200)

        ranking_list = resp.context["ranking_list"]
        totals = [item["score"]["total"] for item in ranking_list]
        self.assertEqual(totals, sorted(totals, reverse=True))

    def test_ranking_user_a_primero(self):
        """user_a tiene más puntos → aparece primero."""
        self.client.login(username="scorer_a", password="pw")
        resp = self.client.get(reverse("ranking", args=[self.t.id]))
        first = resp.context["ranking_list"][0]
        self.assertEqual(first["user"], self.user_a)
        self.assertEqual(first["position"], 1)

    def test_ranking_no_incluye_trofeos_en_seccion_especial(self):
        """La sección de trofeos fue eliminada del ranking."""
        self.client.login(username="scorer_a", password="pw")
        resp = self.client.get(reverse("ranking", args=[self.t.id]))
        # "Trofeos" no debe aparecer como sección del ranking
        self.assertNotContains(resp, "Trofeos")


# ─────────────────────────────────────────────────────────────────────────────
# 6. FLUJO DEADLINE
# ─────────────────────────────────────────────────────────────────────────────

class DeadlineTest(TestCase):
    """Simula que el Mundial ya empezó: deadline en el pasado → endpoints cierran."""

    @classmethod
    def setUpTestData(cls):
        cls.t1 = Team.objects.create(name="TeamX", code="TXX")
        cls.t2 = Team.objects.create(name="TeamY", code="TYY")
        cls.t3 = Team.objects.create(name="TeamZ", code="TZZ")
        cls.t4 = Team.objects.create(name="TeamW", code="TWW")

        # Partido en el PASADO → deadline ya pasó
        cls.past_match = Match.objects.create(
            stage=Match.Stage.GROUP, group="A",
            match_datetime=datetime(2026, 6, 1, 18, 0, tzinfo=timezone.utc),
            home_team=cls.t1, away_team=cls.t2,
        )
        Match.objects.create(
            stage=Match.Stage.GROUP, group="A",
            match_datetime=datetime(2026, 6, 2, 18, 0, tzinfo=timezone.utc),
            home_team=cls.t3, away_team=cls.t4,
        )
        Match.objects.create(
            stage=Match.Stage.GROUP, group="A",
            match_datetime=datetime(2026, 6, 3, 18, 0, tzinfo=timezone.utc),
            home_team=cls.t1, away_team=cls.t3,
        )

        cls.user = User.objects.create_user("deadline_user", password="pw")
        cls.t = Tournament.objects.create(name="T", created_by=cls.user)
        TournamentMember.objects.create(user=cls.user, tournament=cls.t)

    def setUp(self):
        get_tournament_deadline.cache_clear()
        self.client.login(username="deadline_user", password="pw")

    def test_save_group_prediction_retorna_403_tras_deadline(self):
        resp = _post_json(self.client,
            reverse("save_group_prediction", args=[self.t.id, "A"]),
            {"first": self.t1.pk, "second": self.t2.pk, "third": self.t3.pk},
        )
        self.assertEqual(resp.status_code, 403)
        data = json.loads(resp.content)
        self.assertFalse(data["ok"])

    def test_save_terceros_retorna_403_tras_deadline(self):
        resp = _post_json(self.client,
            reverse("save_terceros", args=[self.t.id]),
            {"order": f"{self.t1.pk},{self.t2.pk}"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_bracket_predict_retorna_403_tras_deadline(self):
        r32 = Match.objects.create(
            stage=Match.Stage.ROUND_OF_32,
            match_datetime=_dt(7, 5),
        )
        resp = _post_json(self.client,
            reverse("bracket_predict", args=[self.t.id]),
            {"match_id": r32.id, "winner_team_id": self.t1.pk},
        )
        self.assertEqual(resp.status_code, 403)

    def test_bracket_get_carga_sin_error(self):
        resp = self.client.get(reverse("bracket", args=[self.t.id]))
        self.assertEqual(resp.status_code, 200)
        # is_open=False porque deadline pasó
        self.assertFalse(resp.context["is_open"])

    def test_mis_predicciones_get_carga_con_deadline_pasado(self):
        resp = self.client.get(reverse("mis_predicciones", args=[self.t.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["is_open"])


# ─────────────────────────────────────────────────────────────────────────────
# 7. FLUJO SYNC ENDPOINT
# ─────────────────────────────────────────────────────────────────────────────

SYNC_URL = "/api/sync/world-cup/"
SYNC_TOKEN = "test-token-abc"


@override_settings(SYNC_TOKEN=SYNC_TOKEN)
class SyncEndpointTest(TestCase):

    def setUp(self):
        api_module._last_sync_time = 0.0
        get_tournament_deadline.cache_clear()

    def test_get_retorna_405(self):
        resp = self.client.get(SYNC_URL, HTTP_X_SYNC_TOKEN=SYNC_TOKEN)
        self.assertEqual(resp.status_code, 405)

    def test_sin_token_retorna_401(self):
        resp = self.client.post(SYNC_URL)
        self.assertEqual(resp.status_code, 401)
        self.assertFalse(json.loads(resp.content)["ok"])

    def test_token_incorrecto_retorna_401(self):
        resp = self.client.post(SYNC_URL, HTTP_X_SYNC_TOKEN="wrong-token")
        self.assertEqual(resp.status_code, 401)

    @patch("predictions.api.sync_world_cup_matches")
    def test_token_correcto_retorna_200(self, mock_sync):
        mock_sync.return_value = {"created": 5, "updated": 10, "score_updated": 3, "skipped": 0}
        resp = self.client.post(SYNC_URL, HTTP_X_SYNC_TOKEN=SYNC_TOKEN)
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data["ok"])
        self.assertEqual(data["created"], 5)
        mock_sync.assert_called_once()

    @patch("predictions.api.sync_world_cup_matches")
    def test_segunda_llamada_inmediata_retorna_429(self, mock_sync):
        mock_sync.return_value = {"created": 0, "updated": 0, "score_updated": 0, "skipped": 0}

        # Primera llamada: OK
        resp1 = self.client.post(SYNC_URL, HTTP_X_SYNC_TOKEN=SYNC_TOKEN)
        self.assertEqual(resp1.status_code, 200)

        # Segunda llamada dentro del cooldown de 5 min: 429
        resp2 = self.client.post(SYNC_URL, HTTP_X_SYNC_TOKEN=SYNC_TOKEN)
        self.assertEqual(resp2.status_code, 429)
        data = json.loads(resp2.content)
        self.assertFalse(data["ok"])

    @patch("predictions.api.sync_world_cup_matches")
    def test_error_interno_retorna_500(self, mock_sync):
        from predictions.services.football_data import FootballDataError
        mock_sync.side_effect = FootballDataError("API down")
        resp = self.client.post(SYNC_URL, HTTP_X_SYNC_TOKEN=SYNC_TOKEN)
        self.assertEqual(resp.status_code, 500)
        self.assertFalse(json.loads(resp.content)["ok"])


# ─────────────────────────────────────────────────────────────────────────────
# 8. FLUJO MULTI-TORNEO
# ─────────────────────────────────────────────────────────────────────────────

class MultiTorneoTest(TestCase):
    fixtures = ["teams", "matches"]

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("multi_user", password="pw")
        cls.other = User.objects.create_user("other_user", password="pw")

        cls.ta = Tournament.objects.create(name="Torneo A", created_by=cls.user)
        cls.tb = Tournament.objects.create(name="Torneo B", created_by=cls.user)

        TournamentMember.objects.create(user=cls.user, tournament=cls.ta)
        TournamentMember.objects.create(user=cls.user, tournament=cls.tb)
        TournamentMember.objects.create(user=cls.other, tournament=cls.ta)

    def setUp(self):
        get_tournament_deadline.cache_clear()
        self.client.login(username="multi_user", password="pw")

    def _save_group(self, t_id, letter, first, second, third):
        return _post_json(self.client,
            reverse("save_group_prediction", args=[t_id, letter]),
            {"first": first, "second": second, "third": third},
        )

    def test_predicciones_distintas_en_cada_torneo(self):
        """Predicciones en Torneo A no contaminan Torneo B."""
        fa, sa, ta_ = GROUP_PRED["A"]
        fb, sb, tb_ = GROUP_PRED["B"][:3]  # otros equipos para Torneo B

        # Torneo A: México(1) primero
        self._save_group(self.ta.id, "A", fa, sa, ta_)
        # Torneo B: Canadá(3) primero en grupo B
        self._save_group(self.tb.id, "B", fb, sb, tb_)

        gp_a = GroupPrediction.objects.filter(user=self.user, tournament=self.ta)
        gp_b = GroupPrediction.objects.filter(user=self.user, tournament=self.tb)

        self.assertEqual(gp_a.count(), 1)
        self.assertEqual(gp_b.count(), 1)
        self.assertEqual(gp_a.first().group, "A")
        self.assertEqual(gp_b.first().group, "B")

    def test_scoring_independiente_por_torneo(self):
        """compute_user_score es independiente por torneo."""
        score_a = compute_user_score(self.user, self.ta)
        score_b = compute_user_score(self.user, self.tb)
        # Sin resultados reales, ambos valen 0 pero son consultas independientes
        self.assertEqual(score_a["total"], 0)
        self.assertEqual(score_b["total"], 0)

    def test_usuario_no_miembro_redirigido(self):
        """Un usuario no miembro no puede ver el bracket de un torneo ajeno."""
        stranger = User.objects.create_user("stranger", password="pw")
        self.client.login(username="stranger", password="pw")
        resp = self.client.get(reverse("bracket", args=[self.ta.id]), follow=True)
        # Redirige a mis_torneos con mensaje de error
        self.assertRedirects(resp, reverse("mis_torneos"))

    def test_mis_torneos_muestra_solo_torneos_propios(self):
        """Torneo B no aparece en la vista de other_user."""
        self.client.login(username="other_user", password="pw")
        resp = self.client.get(reverse("mis_torneos"))
        self.assertContains(resp, "Torneo A")
        self.assertNotContains(resp, "Torneo B")

    def test_ranking_aislado_por_torneo(self):
        """El ranking de Torneo A no incluye miembros de Torneo B."""
        self.client.login(username="multi_user", password="pw")
        resp = self.client.get(reverse("ranking", args=[self.ta.id]))
        self.assertEqual(resp.status_code, 200)
        usernames = [item["user"].username for item in resp.context["ranking_list"]]
        # multi_user y other_user están en Torneo A
        self.assertIn("multi_user", usernames)
        self.assertIn("other_user", usernames)

        resp_b = self.client.get(reverse("ranking", args=[self.tb.id]))
        usernames_b = [item["user"].username for item in resp_b.context["ranking_list"]]
        # other_user NO está en Torneo B
        self.assertIn("multi_user", usernames_b)
        self.assertNotIn("other_user", usernames_b)


# ─────────────────────────────────────────────────────────────────────────────
# 9. RANKING — CAMPEÓN Y SUBCAMPEÓN
# ─────────────────────────────────────────────────────────────────────────────

class RankingFinalPicksTest(TestCase):
    """
    Verifica que el ranking muestre correctamente el campeón y subcampeón
    predichos por cada usuario, derivados de sus predicciones de Semis + Final.
    """

    @classmethod
    def setUpTestData(cls):
        cls.argentina = Team.objects.create(name="Argentina", code="ARG")
        cls.francia   = Team.objects.create(name="Francia",   code="FRA")
        cls.brasil    = Team.objects.create(name="Brasil",    code="BRA")
        cls.alemania  = Team.objects.create(name="Alemania",  code="GER")

        # 2 semifinales + 1 final (orden cronológico)
        cls.sf0 = Match.objects.create(
            stage=Match.Stage.SEMI_FINAL,
            match_datetime=_dt(7, 29),
        )
        cls.sf1 = Match.objects.create(
            stage=Match.Stage.SEMI_FINAL,
            match_datetime=_dt(7, 30),
        )
        cls.final_m = Match.objects.create(
            stage=Match.Stage.FINAL,
            match_datetime=_dt(8, 1),
        )

        # user_completo: Argentina gana SF[0], Francia gana SF[1], Argentina campeona
        # user_incompleto: solo predice Final (Argentina) pero sin SF → runner_up = None
        # user_sin_preds: sin predicciones de bracket
        cls.user_completo   = User.objects.create_user("completo",   password="pw")
        cls.user_incompleto = User.objects.create_user("incompleto", password="pw")
        cls.user_sin_preds  = User.objects.create_user("sin_preds",  password="pw")

        cls.t = Tournament.objects.create(name="T", created_by=cls.user_completo)
        for u in [cls.user_completo, cls.user_incompleto, cls.user_sin_preds]:
            TournamentMember.objects.create(user=u, tournament=cls.t)

        # user_completo: Argentina gana SF[0], Francia gana SF[1], Argentina campeona
        BracketPrediction.objects.create(
            user=cls.user_completo, tournament=cls.t,
            match=cls.sf0, predicted_winner=cls.argentina,
        )
        BracketPrediction.objects.create(
            user=cls.user_completo, tournament=cls.t,
            match=cls.sf1, predicted_winner=cls.francia,
        )
        BracketPrediction.objects.create(
            user=cls.user_completo, tournament=cls.t,
            match=cls.final_m, predicted_winner=cls.argentina,
        )

        # user_incompleto: predice Final pero sin SF
        BracketPrediction.objects.create(
            user=cls.user_incompleto, tournament=cls.t,
            match=cls.final_m, predicted_winner=cls.argentina,
        )

    def setUp(self):
        get_tournament_deadline.cache_clear()
        self.client.login(username="completo", password="pw")

    def _ranking(self):
        resp = self.client.get(reverse("ranking", args=[self.t.id]))
        self.assertEqual(resp.status_code, 200)
        by_user = {item["user"].username: item for item in resp.context["ranking_list"]}
        return by_user

    # ── Contexto: champion y runner_up ────────────────────────────────────────

    def test_usuario_con_final_completa_tiene_campeon_y_subcampeon(self):
        picks = self._ranking()["completo"]
        self.assertIsNotNone(picks["champion"])
        self.assertEqual(picks["champion"].pk, self.argentina.pk)
        self.assertIsNotNone(picks["runner_up"])
        self.assertEqual(picks["runner_up"].pk, self.francia.pk)

    def test_usuario_con_solo_final_tiene_campeon_pero_sin_subcampeon(self):
        """Sin predicciones de Semis no se puede determinar el subcampeón."""
        picks = self._ranking()["incompleto"]
        self.assertIsNotNone(picks["champion"])
        self.assertEqual(picks["champion"].pk, self.argentina.pk)
        self.assertIsNone(picks["runner_up"])

    def test_usuario_sin_predicciones_tiene_nulos(self):
        picks = self._ranking()["sin_preds"]
        self.assertIsNone(picks["champion"])
        self.assertIsNone(picks["runner_up"])

    def test_campeon_y_subcampeon_independientes_por_torneo(self):
        """Predicciones de otro torneo no contaminan."""
        otro_torneo = Tournament.objects.create(name="Otro", created_by=self.user_completo)
        TournamentMember.objects.create(user=self.user_completo, tournament=otro_torneo)
        # Sin predicciones en otro_torneo → champion debe ser None
        resp = self.client.get(reverse("ranking", args=[otro_torneo.id]))
        item = resp.context["ranking_list"][0]
        self.assertIsNone(item["champion"])

    # ── HTML: banderas y nombres ──────────────────────────────────────────────

    def test_html_muestra_nombre_del_campeon(self):
        resp = self.client.get(reverse("ranking", args=[self.t.id]))
        self.assertContains(resp, "Argentina")

    def test_html_muestra_nombre_del_subcampeon(self):
        resp = self.client.get(reverse("ranking", args=[self.t.id]))
        self.assertContains(resp, "Francia")

    def test_html_muestra_guion_para_usuario_sin_prediccion(self):
        """El guion "—" aparece para usuarios sin Final predicha."""
        resp = self.client.get(reverse("ranking", args=[self.t.id]))
        self.assertContains(resp, "—")

    def test_html_incluye_url_de_bandera_argentina(self):
        """La bandera de Argentina (flagcdn.com/w40/ar.png) aparece en el HTML."""
        resp = self.client.get(reverse("ranking", args=[self.t.id]))
        self.assertContains(resp, "flagcdn.com")
        self.assertContains(resp, "/ar.png")
