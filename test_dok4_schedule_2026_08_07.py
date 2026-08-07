import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("TRELLO_KEY", "test-key")
os.environ.setdefault("TRELLO_TOKEN", "test-token")

import app
from update_dok4_plan_local import build_state, summary


ROOT = Path(__file__).parent
DOCUMENT = json.loads(
    (ROOT / "dok4_schedule_2026-08-07.json").read_text(encoding="utf-8")
)
ROWS = DOCUMENT["rows"]


class FakeTrello:
    def __init__(self):
        self.list_id = "series-list"
        self.cards = [{
            "id": f"card-{index}", "name": f"{row['scene_id']}. Test",
            "desc": "Ručný obsah karty", "idList": self.list_id,
            "shortUrl": f"https://trello.com/c/card{index}", "due": None,
            "dueComplete": False, "pos": (index + 1) * 16384, "closed": False,
        } for index, row in enumerate(ROWS)]

    def get(self, path, params=None):
        if path == "/boards/lzNy4AtY":
            return {"id": "board-id", "name": "DOK 4",
                    "url": "https://trello.com/b/lzNy4AtY/dok-4", "shortLink": "lzNy4AtY"}
        if path == "/boards/board-id/lists":
            return [{"id": self.list_id, "name": "VŠETKY EPIZÓDY",
                     "pos": 16384, "closed": False}]
        if path == f"/lists/{self.list_id}/cards":
            return self.cards
        raise AssertionError((path, params))


class Dok4August7ScheduleTests(unittest.TestCase):
    def test_authoritative_json_and_next_seven_shooting_days(self):
        self.assertEqual(DOCUMENT["source"]["dated"], "2026-08-07")
        self.assertTrue(DOCUMENT["source"]["file"].endswith("plan update 7.8.pdf"))
        self.assertEqual(len(ROWS), 160)
        self.assertEqual(len({row["scene_id"] for row in ROWS}), 160)
        state = build_state(FakeTrello(), ROWS, source_date="2026-08-07", as_of="2026-08-07")
        report = summary(state, ROWS)
        self.assertEqual(report["missing_count"], 0)
        self.assertEqual(report["duplicate_scene_ids_count"], 0)
        self.assertEqual(report["fallback_collision_count"], 0)
        self.assertEqual(report["shooting_dates"], [
            "2026-08-09", "2026-08-10", "2026-08-12", "2026-08-13",
            "2026-08-14", "2026-08-16", "2026-08-18",
        ])

    def test_endpoint_rejects_a_different_as_of_date(self):
        response = app.app.test_client().post(
            "/api/sync-dok4-current-schedule?mode=dry-run&as_of=2026-08-08",
            headers={"X-Sync-Key": app.DOK4_CURRENT_SCHEDULE_KEY},
        )
        self.assertEqual(response.status_code, 400)

    def test_prop_dry_run_reports_only_real_date_changes(self):
        scene = {
            "id": "scene", "name": "08/1. Test", "desc": "", "due": "2026-08-09T10:00:00.000Z",
            "dueComplete": False, "shortUrl": "https://trello.com/c/scene", "closed": False,
            "idList": "series", "checklists": [{"name": "Rekvizity", "checkItems": [{"name": "[z] Kufor"}]}],
        }
        todo = {
            "id": "todo-card", "name": "Kufor - 08/1. Test", "desc": "", "due": "2026-08-02T10:00:00.000Z",
            "shortUrl": "https://trello.com/c/todo", "closed": False, "pos": 1,
        }

        def fake_get(path, params=None):
            if path == "/boards/lzNy4AtY":
                return {"id": "board", "name": "DOK 4", "url": "https://trello.com/b/lzNy4AtY"}
            if path == "/boards/board/lists":
                return [{"id": "series", "name": "VŠETKY EPIZÓDY", "pos": 1, "closed": False},
                        {"id": "todo", "name": "ToDo", "pos": 2, "closed": False}]
            if path == "/lists/series/cards":
                return [scene]
            if path == "/lists/todo/cards":
                return [todo]
            raise AssertionError((path, params))

        with patch.object(app, "trello_get", side_effect=fake_get):
            response = app.app.test_client().post(
                "/api/sync-dok4-prop-cards?mode=dry-run",
                headers={"X-Prop-Sync-Key": "dunaj-props-sync-7f32b861"},
            )
        payload = response.get_json()
        self.assertEqual(payload["to_update"], 1)
        self.assertEqual(payload["unchanged"], 0)
        self.assertIn("due", payload["sample"][0]["fields"])
        self.assertEqual(payload["sample"][0]["desired_due"][:10], "2026-08-09")


if __name__ == "__main__":
    unittest.main()
