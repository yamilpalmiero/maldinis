"""
Tests for predictions/utils.py — get_tournament_deadline() and require_before_deadline.
Also covers deadline enforcement in bracket_predict, save_group_prediction, save_terceros.
"""
from datetime import datetime, timezone as tz
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.utils import timezone

from predictions.models import Match, Team
from predictions.utils import get_tournament_deadline, require_before_deadline


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_match(day, hour=12):
    return Match.objects.create(
        stage=Match.Stage.GROUP,
        group="A",
        match_datetime=datetime(2026, 6, day, hour, 0, tzinfo=tz.utc),
    )


# ── get_tournament_deadline() ─────────────────────────────────────────────────

class GetTournamentDeadlineTest(TestCase):

    def setUp(self):
        get_tournament_deadline.cache_clear()

    def tearDown(self):
        get_tournament_deadline.cache_clear()

    def test_returns_none_when_no_matches(self):
        self.assertIsNone(get_tournament_deadline())

    def test_returns_earliest_match_datetime(self):
        _make_match(day=15)
        _make_match(day=11)  # earlier
        _make_match(day=20)
        deadline = get_tournament_deadline()
        self.assertEqual(deadline.day, 11)

    def test_result_is_timezone_aware(self):
        _make_match(day=11)
        deadline = get_tournament_deadline()
        self.assertIsNotNone(deadline.tzinfo)

    def test_cache_returns_same_object(self):
        _make_match(day=11)
        first  = get_tournament_deadline()
        second = get_tournament_deadline()
        self.assertIs(first, second)


# ── require_before_deadline decorator ────────────────────────────────────────

class RequireBeforeDeadlineTest(TestCase):

    def setUp(self):
        get_tournament_deadline.cache_clear()

    def tearDown(self):
        get_tournament_deadline.cache_clear()

    def _view(self, request):
        from django.http import JsonResponse
        return JsonResponse({"ok": True})

    def _make_request(self):
        from django.test import RequestFactory
        return RequestFactory().post("/")

    def test_passes_through_before_deadline(self):
        _make_match(day=30)  # far in the future relative to mocked now
        decorated = require_before_deadline(self._view)
        past_time  = datetime(2026, 6, 1, tzinfo=tz.utc)
        with patch("predictions.utils._now", return_value=past_time):
            resp = decorated(self._make_request())
        self.assertEqual(resp.status_code, 200)

    def test_blocks_after_deadline(self):
        _make_match(day=11)
        decorated = require_before_deadline(self._view)
        after_deadline = datetime(2026, 6, 12, tzinfo=tz.utc)
        with patch("predictions.utils._now", return_value=after_deadline):
            resp = decorated(self._make_request())
        self.assertEqual(resp.status_code, 403)
        import json
        data = json.loads(resp.content)
        self.assertFalse(data["ok"])
        self.assertIn("cerraron", data["error"])

    def test_passes_through_when_no_matches(self):
        # No matches → deadline is None → always open
        decorated = require_before_deadline(self._view)
        far_future = datetime(2030, 1, 1, tzinfo=tz.utc)
        with patch("predictions.utils._now", return_value=far_future):
            resp = decorated(self._make_request())
        self.assertEqual(resp.status_code, 200)


# ── View endpoint enforcement ─────────────────────────────────────────────────

class DeadlineViewEnforcementTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("deadlineuser", password="pw")
        from tournaments.models import Tournament, TournamentMember
        cls.tournament = Tournament.objects.create(name="T", created_by=cls.user)
        TournamentMember.objects.create(tournament=cls.tournament, user=cls.user)

        cls.t1 = Team.objects.create(name="TA", code="TAA")
        cls.t2 = Team.objects.create(name="TB", code="TBB")

        cls.match = Match.objects.create(
            stage=Match.Stage.ROUND_OF_32,
            match_datetime=datetime(2026, 6, 15, 12, 0, tzinfo=tz.utc),
            home_team=cls.t1,
            away_team=cls.t2,
        )

    def setUp(self):
        get_tournament_deadline.cache_clear()
        self.client.login(username="deadlineuser", password="pw")
        # Also create a group match so deadline function has something to return
        self._group_match = Match.objects.create(
            stage=Match.Stage.GROUP,
            group="A",
            match_datetime=datetime(2026, 6, 11, 15, 0, tzinfo=tz.utc),
        )

    def tearDown(self):
        get_tournament_deadline.cache_clear()
        self._group_match.delete()

    def _post_bracket(self, team_id):
        import json
        return self.client.post(
            f"/torneo/{self.tournament.id}/bracket/predict/",
            data=json.dumps({"match_id": self.match.id, "winner_team_id": team_id}),
            content_type="application/json",
        )

    def _post_group(self, first_id):
        import json
        return self.client.post(
            f"/torneo/{self.tournament.id}/mis-predicciones/grupo/A/",
            data=json.dumps({"first": first_id, "second": None, "third": None}),
            content_type="application/json",
        )

    def _post_terceros(self, order):
        import json
        return self.client.post(
            f"/torneo/{self.tournament.id}/mis-predicciones/terceros/",
            data=json.dumps({"order": order}),
            content_type="application/json",
        )

    # ── Pre-deadline: saves work ──────────────────────────────────────────────

    def test_bracket_save_allowed_before_deadline(self):
        before = datetime(2026, 6, 10, tzinfo=tz.utc)
        with patch("predictions.utils._now", return_value=before):
            resp = self._post_bracket(self.t1.id)
        self.assertNotEqual(resp.status_code, 403)

    def test_group_save_allowed_before_deadline(self):
        before = datetime(2026, 6, 10, tzinfo=tz.utc)
        # Need group-stage match with these teams
        Match.objects.create(
            stage=Match.Stage.GROUP, group="A",
            match_datetime=datetime(2026, 6, 12, tzinfo=tz.utc),
            home_team=self.t1, away_team=self.t2,
        )
        with patch("predictions.utils._now", return_value=before):
            resp = self._post_group(self.t1.id)
        self.assertNotEqual(resp.status_code, 403)

    # ── Post-deadline: saves blocked with 403 ────────────────────────────────

    def test_bracket_save_blocked_after_deadline(self):
        after = datetime(2026, 6, 12, tzinfo=tz.utc)
        with patch("predictions.utils._now", return_value=after):
            resp = self._post_bracket(self.t1.id)
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(resp.json()["ok"])

    def test_group_save_blocked_after_deadline(self):
        after = datetime(2026, 6, 12, tzinfo=tz.utc)
        with patch("predictions.utils._now", return_value=after):
            resp = self._post_group(self.t1.id)
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(resp.json()["ok"])

    def test_terceros_save_blocked_after_deadline(self):
        after = datetime(2026, 6, 12, tzinfo=tz.utc)
        with patch("predictions.utils._now", return_value=after):
            resp = self._post_terceros(f"{self.t1.id}")
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(resp.json()["ok"])
