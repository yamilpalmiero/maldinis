"""
Tests for the Player model and sync_players() service.
"""
from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from predictions.models import Player, Team
from predictions.services.football_data import FootballDataError, sync_players


# ── Helpers ──────────────────────────────────────────────────────────────────

def _api_team(tla, squad):
    return {"tla": tla, "squad": squad}


def _api_player(ext_id, name, position="Offence", shirt=None, dob=None):
    p = {"id": ext_id, "name": name, "position": position}
    if shirt is not None:
        p["shirtNumber"] = shirt
    if dob is not None:
        p["dateOfBirth"] = dob
    return p


# ── Model tests ───────────────────────────────────────────────────────────────

class PlayerModelTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Argentina", code="ARG")

    def test_str(self):
        p = Player(name="Lionel Messi", team=self.team)
        self.assertEqual(str(p), "Lionel Messi (ARG)")

    def test_defaults(self):
        p = Player.objects.create(name="Test", team=self.team)
        self.assertTrue(p.is_active)
        self.assertIsNone(p.external_id)
        self.assertEqual(p.position, "")

    def test_position_choices(self):
        p = Player.objects.create(
            name="Emi Martínez", team=self.team,
            position=Player.Position.GOALKEEPER,
        )
        self.assertEqual(p.position, "GK")


# ── sync_players tests ────────────────────────────────────────────────────────

class SyncPlayersTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.team_arg = Team.objects.create(name="Argentina", code="ARG")
        cls.team_bra = Team.objects.create(name="Brasil", code="BRA")

    @patch("predictions.services.football_data.requests.get")
    def test_creates_players(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"teams": [
            _api_team("ARG", [
                _api_player(101, "Lionel Messi",     "Offence",    10, "1987-06-24"),
                _api_player(102, "Emiliano Martínez","Goalkeeper", 23, "1992-09-02"),
            ]),
        ]}

        result = sync_players()

        self.assertEqual(result["created"], 2)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(Player.objects.count(), 2)

        messi = Player.objects.get(external_id=101)
        self.assertEqual(messi.name, "Lionel Messi")
        self.assertEqual(messi.position, Player.Position.FORWARD)
        self.assertEqual(messi.shirt_number, 10)
        self.assertEqual(messi.date_of_birth, date(1987, 6, 24))

        emi = Player.objects.get(external_id=102)
        self.assertEqual(emi.position, Player.Position.GOALKEEPER)

    @patch("predictions.services.football_data.requests.get")
    def test_updates_existing_player(self, mock_get):
        Player.objects.create(
            name="Old Name", team=self.team_arg,
            external_id=101, shirt_number=99,
        )
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"teams": [
            _api_team("ARG", [_api_player(101, "Lionel Messi", shirt=10)]),
        ]}

        result = sync_players()

        self.assertEqual(result["created"], 0)
        self.assertEqual(result["updated"], 1)
        p = Player.objects.get(external_id=101)
        self.assertEqual(p.name, "Lionel Messi")
        self.assertEqual(p.shirt_number, 10)

    @patch("predictions.services.football_data.requests.get")
    def test_deactivates_missing_players(self, mock_get):
        Player.objects.create(
            name="Dropped Player", team=self.team_arg,
            external_id=999, is_active=True,
        )
        # API returns empty squad for ARG → player 999 not seen
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"teams": [
            _api_team("ARG", []),
        ]}

        result = sync_players()

        self.assertEqual(result["deactivated"], 1)
        self.assertFalse(Player.objects.get(external_id=999).is_active)

    @patch("predictions.services.football_data.requests.get")
    def test_skips_unknown_team_tla(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"teams": [
            _api_team("ZZZ", [_api_player(1, "Unknown Player")]),  # no Team with code ZZZ
        ]}

        result = sync_players()

        self.assertEqual(result["created"], 0)
        self.assertEqual(Player.objects.count(), 0)

    @patch("predictions.services.football_data.requests.get")
    def test_raises_on_403(self, mock_get):
        mock_get.return_value.status_code = 403
        mock_get.return_value.text = "Forbidden"

        with self.assertRaises(FootballDataError) as ctx:
            sync_players()
        self.assertIn("paid", str(ctx.exception))

    @patch("predictions.services.football_data.requests.get")
    def test_raises_on_429(self, mock_get):
        mock_get.return_value.status_code = 429
        mock_get.return_value.text = "Too Many Requests"

        with self.assertRaises(FootballDataError):
            sync_players()


# ── Admin smoke test ──────────────────────────────────────────────────────────

class PlayerAdminTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser("admin_tester", password="pw")
        cls.team = Team.objects.create(name="Argentina", code="ARG")
        Player.objects.create(name="Test Player", team=cls.team, position="FWD")

    def setUp(self):
        self.client.login(username="admin_tester", password="pw")

    def test_changelist_returns_200(self):
        url = reverse("admin:predictions_player_changelist")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_changelist_shows_player(self):
        url = reverse("admin:predictions_player_changelist")
        resp = self.client.get(url)
        self.assertContains(resp, "Test Player")
