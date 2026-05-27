"""
Tests for the POST /api/sync/world-cup/ endpoint.
"""
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

import predictions.api as api_module

GOOD_TOKEN = "test-secret-token-abc123"
ENDPOINT = "/api/sync/world-cup/"

SYNC_RESULT = {"created": 2, "updated": 5, "score_updated": 3, "skipped": 0}


class SyncEndpointAuthTest(TestCase):

    def setUp(self):
        api_module._last_sync_time = 0.0

    @override_settings(SYNC_TOKEN=GOOD_TOKEN)
    @patch("predictions.api.sync_world_cup_matches", return_value=SYNC_RESULT)
    def test_valid_token_returns_200_and_stats(self, mock_sync):
        resp = self.client.post(ENDPOINT, HTTP_X_SYNC_TOKEN=GOOD_TOKEN)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["created"], 2)
        self.assertEqual(data["updated"], 5)
        self.assertEqual(data["score_updated"], 3)
        mock_sync.assert_called_once()

    @override_settings(SYNC_TOKEN=GOOD_TOKEN)
    def test_missing_token_returns_401(self):
        resp = self.client.post(ENDPOINT)
        self.assertEqual(resp.status_code, 401)
        self.assertFalse(resp.json()["ok"])

    @override_settings(SYNC_TOKEN=GOOD_TOKEN)
    def test_wrong_token_returns_401(self):
        resp = self.client.post(ENDPOINT, HTTP_X_SYNC_TOKEN="wrong-token")
        self.assertEqual(resp.status_code, 401)

    @override_settings(SYNC_TOKEN="")
    def test_unconfigured_token_always_returns_401(self):
        # SYNC_TOKEN not set in env → endpoint locked regardless of what's sent
        resp = self.client.post(ENDPOINT, HTTP_X_SYNC_TOKEN="")
        self.assertEqual(resp.status_code, 401)

    @override_settings(SYNC_TOKEN=GOOD_TOKEN)
    def test_get_returns_405(self):
        resp = self.client.get(ENDPOINT, HTTP_X_SYNC_TOKEN=GOOD_TOKEN)
        self.assertEqual(resp.status_code, 405)


class SyncEndpointCooldownTest(TestCase):

    def setUp(self):
        api_module._last_sync_time = 0.0

    @override_settings(SYNC_TOKEN=GOOD_TOKEN)
    @patch("predictions.api.sync_world_cup_matches", return_value=SYNC_RESULT)
    def test_second_call_within_cooldown_returns_429(self, mock_sync):
        self.client.post(ENDPOINT, HTTP_X_SYNC_TOKEN=GOOD_TOKEN)
        resp = self.client.post(ENDPOINT, HTTP_X_SYNC_TOKEN=GOOD_TOKEN)
        self.assertEqual(resp.status_code, 429)
        data = resp.json()
        self.assertFalse(data["ok"])
        self.assertIn("Wait", data["error"])
        # sync was only called once (second call blocked by cooldown)
        mock_sync.assert_called_once()

    @override_settings(SYNC_TOKEN=GOOD_TOKEN)
    @patch("predictions.api.sync_world_cup_matches", return_value=SYNC_RESULT)
    def test_call_after_cooldown_expires_succeeds(self, mock_sync):
        import time
        # Simulate last sync happened more than COOLDOWN_SECONDS ago
        api_module._last_sync_time = time.time() - api_module._COOLDOWN_SECONDS - 1
        resp = self.client.post(ENDPOINT, HTTP_X_SYNC_TOKEN=GOOD_TOKEN)
        self.assertEqual(resp.status_code, 200)
        mock_sync.assert_called_once()


class SyncEndpointErrorTest(TestCase):

    def setUp(self):
        api_module._last_sync_time = 0.0

    @override_settings(SYNC_TOKEN=GOOD_TOKEN)
    @patch("predictions.api.sync_world_cup_matches")
    def test_football_data_error_returns_500_with_message(self, mock_sync):
        from predictions.services.football_data import FootballDataError
        mock_sync.side_effect = FootballDataError("Rate limit alcanzado.")
        resp = self.client.post(ENDPOINT, HTTP_X_SYNC_TOKEN=GOOD_TOKEN)
        self.assertEqual(resp.status_code, 500)
        data = resp.json()
        self.assertFalse(data["ok"])
        self.assertIn("Rate limit", data["error"])

    @override_settings(SYNC_TOKEN=GOOD_TOKEN)
    @patch("predictions.api.sync_world_cup_matches")
    def test_unexpected_exception_returns_500_generic(self, mock_sync):
        mock_sync.side_effect = RuntimeError("something exploded")
        resp = self.client.post(ENDPOINT, HTTP_X_SYNC_TOKEN=GOOD_TOKEN)
        self.assertEqual(resp.status_code, 500)
        data = resp.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"], "Internal server error")
