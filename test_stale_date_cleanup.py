import os
import unittest
from unittest.mock import patch

os.environ.setdefault("TRELLO_KEY", "test-key")
os.environ.setdefault("TRELLO_TOKEN", "test-token")

import app
from update_dok4_plan_local import apply, cleanup_stale


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

    def test_dok4_metadata_keeps_due_only_inside_active_window(self):
        class CapturingTrello:
            def __init__(self):
                self.payloads = {}

            def put(self, path, payload):
                self.payloads[path] = payload
                return {"shortUrl": "https://trello.com/c/test"}

        def row(scene_id, date):
            return {
                "scene_id": scene_id, "shooting_day": 1, "shooting_date": date,
                "order": 1, "unit": "1st unit", "location": "LOKÁCIA", "characters": "POSTAVA",
            }

        active_row = row("01/1", "2026-08-10")
        future_row = row("01/2", "2026-08-20")
        state = {
            "board": {"shortLink": "lzNy4AtY"}, "duplicates": [], "reused_cards": [],
            "duplicate_target_lists": {}, "anchor": {"id": "series"}, "lists_by_name": {},
            "matches": [
                {"row": active_row, "card": {"id": "active", "desc": "", "due": None,
                                              "shortUrl": "https://trello.com/c/active"}},
                {"row": future_row, "card": {"id": "future", "desc": "",
                                              "due": "2026-08-20T10:00:00.000Z",
                                              "shortUrl": "https://trello.com/c/future"}},
            ],
            "shooting_dates": ["2026-08-10"], "source_date": "2026-08-09",
        }
        trello = CapturingTrello()
        result = apply(trello, state, metadata_only=True)
        self.assertEqual(result["metadata_errors_count"], 0)
        self.assertEqual(trello.payloads["/cards/active"]["due"], "2026-08-10T10:00:00.000Z")
        self.assertEqual(trello.payloads["/cards/future"]["due"], "")

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
