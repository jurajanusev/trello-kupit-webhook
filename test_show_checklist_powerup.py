import unittest

from app import app


class ShowChecklistPowerUpRoutesTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_connector_page_is_served(self):
        with self.client.get("/powerup/") as response, self.client.get("/powerup/client.js") as client:
            self.assertEqual(200, response.status_code)
            self.assertIn(b"TrelloPowerUp.initialize", response.data + client.data)

    def test_powerup_assets_are_served(self):
        for path in ("core.js", "trello-rest.js", "client.js", "settings.html", "checklists.html", "icon.svg"):
            with self.subTest(path=path):
                with self.client.get(f"/powerup/{path}") as response:
                    self.assertEqual(200, response.status_code)

    def test_powerup_health(self):
        with self.client.get("/powerup/health") as response:
            self.assertEqual(200, response.status_code)
            self.assertEqual("dunaj-show-checklist-powerup", response.get_json()["app"])

    def test_powerup_config_exposes_only_public_api_key(self):
        with self.client.get("/powerup/config.js") as response:
            self.assertEqual(200, response.status_code)
            self.assertIn(b"ShowChecklistConfig", response.data)
            self.assertIn(b"appKey", response.data)
            self.assertNotIn(b"TRELLO_TOKEN", response.data)
            self.assertEqual("no-store", response.headers["Cache-Control"])


if __name__ == "__main__":
    unittest.main()
