import os
import unittest
from unittest.mock import patch

os.environ.setdefault("TRELLO_KEY", "test-key")
os.environ.setdefault("TRELLO_TOKEN", "test-token")

import app
from update_dok4_plan_local import cleanup_stale


class FakeDok4Trello:
    def __init__(self):
        self.payload = None

    def put(self, path, payload):
        self.payload = payload
        return {"name": "07/15. Test", "shortUrl": "https://trello.com/c/test"}


class StaleDateCleanupTests(unittest.TestCase):
    def test_dok4_return_clears_due_and_completion(self):
        trello = FakeDok4Trello()
        state = {
            "board": {"shortLink": "lzNy4AtY"},
            "anchor": {"id": "series", "name": "VŠETKY EPIZÓDY"},
            "stale_window_cards": [{"id": "card", "idList": "old-list"}],
            "lists_by_id": {"old-list": {"name": "14.8."}},
        }
        result = cleanup_stale(trello, state)
        self.assertEqual(trello.payload, {
            "idList": "series", "pos": "bottom", "due": "", "dueComplete": False,
        })
        self.assertTrue(result[0]["due_cleared"])

    def test_microsoft_sync_clears_due_when_trello_todo_has_none(self):
        todo_card = {
            "id": "card", "name": "Rekvizita", "desc": "", "due": None,
            "shortUrl": "https://trello.com/c/prop", "closed": False, "pos": 1,
        }
        task = {
            "id": "task", "title": "Rekvizita",
            "body": {"content": (
                "SYNC PROJECT: DOK4\nSYNC DUE DATE: 2026-08-14\n\n"
                "Trello: https://trello.com/c/prop"
            )},
            "dueDateTime": {"dateTime": "2026-08-13T22:00:00.0000000", "timeZone": "UTC"},
        }

        def fake_trello_get(path, params=None):
            if path == "/boards/lzNy4AtY/lists":
                return [{"id": "todo", "name": "ToDo", "closed": False}]
            if path == "/lists/todo/cards":
                return [todo_card]
            raise AssertionError((path, params))

        with (
            patch.object(app, "microsoft_enabled", return_value=True),
            patch.object(app, "trello_get", side_effect=fake_trello_get),
            patch.object(app, "get_microsoft_access_token", return_value="token"),
            patch.object(app, "graph_get_all", return_value=[task]),
        ):
            response = app.app.test_client().post(
                "/api/sync-dok4-microsoft-todo?mode=dry-run",
                headers={"X-Microsoft-Sync-Key": "dunaj-ms-todo-sync-19jul-84c2f1a7"},
            )
        payload = response.get_json()
        self.assertEqual(payload["to_update"], 1)
        self.assertEqual(payload["sample"][0]["fields"], ["body", "dueDateTime"])


if __name__ == "__main__":
    unittest.main()
