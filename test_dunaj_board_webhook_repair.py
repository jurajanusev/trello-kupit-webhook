import sys
import types
import unittest

flask = types.ModuleType("flask")
flask.jsonify = lambda value: value
flask.request = types.SimpleNamespace(headers={}, args={})
sys.modules.setdefault("flask", flask)

from dunaj_board_webhook_repair import CALLBACK_URL, classify_webhooks


class DunajBoardWebhookTests(unittest.TestCase):
    def test_dunaj_list_subscription_is_not_board_wide(self):
        boards = {"dunaj": {"id": "bd"}, "riverdale": {"id": "br"}}
        hooks = [{"id": "h1", "idModel": "series-17-18", "active": True,
                  "callbackURL": CALLBACK_URL}]
        rows = classify_webhooks(hooks, boards, {"series-17-18": "bd"})
        self.assertEqual(rows[0]["project"], "dunaj")
        self.assertEqual(rows[0]["model_type"], "list")

    def test_dunaj_board_subscription_covers_arbitrary_lists(self):
        boards = {"dunaj": {"id": "bd"}, "riverdale": {"id": "br"}}
        hooks = [{"id": "h1", "idModel": "bd", "active": True,
                  "callbackURL": CALLBACK_URL}]
        rows = classify_webhooks(hooks, boards, {})
        self.assertEqual(rows[0]["project"], "dunaj")
        self.assertEqual(rows[0]["model_type"], "board")

    def test_existing_riverdale_board_behavior_is_preserved(self):
        boards = {"dunaj": {"id": "bd"}, "riverdale": {"id": "br"}}
        hooks = [{"id": "h1", "idModel": "br", "active": True,
                  "callbackURL": CALLBACK_URL}]
        rows = classify_webhooks(hooks, boards, {})
        self.assertEqual(rows[0]["project"], "riverdale")
        self.assertTrue(rows[0]["is_production_callback"])


if __name__ == "__main__":
    unittest.main()
