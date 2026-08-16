import json
import os
import unittest
from pathlib import Path

os.environ.setdefault("TRELLO_KEY", "test-key")
os.environ.setdefault("TRELLO_TOKEN", "test-token")

import app
from update_dok4_plan_local import build_state, summary


ROOT = Path(__file__).parent
DOCUMENT = json.loads(
    (ROOT / "dok4_schedule_2026-08-16.json").read_text(encoding="utf-8")
)
ROWS = DOCUMENT["rows"]


class FakeTrello:
    def __init__(self):
        self.list_id = "series-list"
        self.cards = [{
            "id": f"card-{index}", "name": f"{row['scene_id']}. Test",
            "desc": "Manual content", "idList": self.list_id,
            "shortUrl": f"https://trello.com/c/card{index}", "due": None,
            "dueComplete": False, "pos": (index + 1) * 16384, "closed": False,
        } for index, row in enumerate(ROWS)]

    def get(self, path, params=None):
        if path == "/boards/lzNy4AtY":
            return {"id": "board-id", "name": "DOK 4",
                    "url": "https://trello.com/b/lzNy4AtY/dok-4", "shortLink": "lzNy4AtY"}
        if path == "/boards/board-id/lists":
            return [{"id": self.list_id, "name": "VSETKY EPIZODY",
                     "pos": 16384, "closed": False}]
        if path == f"/lists/{self.list_id}/cards":
            return self.cards
        raise AssertionError((path, params))


class Dok4August16ScheduleTests(unittest.TestCase):
    def test_source_is_unique_and_selects_seven_shooting_days(self):
        self.assertEqual(DOCUMENT["source"]["dated"], "2026-08-16")
        self.assertTrue(DOCUMENT["source"]["file"].endswith("PLAN DOK UPDATE 16.8.pdf"))
        self.assertEqual(len(ROWS), 287)
        self.assertEqual(len({row["scene_id"] for row in ROWS}), 287)
        state = build_state(FakeTrello(), ROWS, source_date="2026-08-16", as_of="2026-08-16")
        report = summary(state, ROWS)
        self.assertEqual(report["missing_count"], 0)
        self.assertEqual(report["duplicate_scene_ids_count"], 0)
        self.assertEqual(report["fallback_collision_count"], 0)
        self.assertEqual(report["shooting_dates"], [
            "2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21",
            "2026-08-23", "2026-08-24", "2026-08-25",
        ])

    def test_completed_endpoint_is_disabled(self):
        response = app.app.test_client().post(
            "/api/sync-dok4-current-schedule?mode=dry-run&as_of=2026-08-16",
            headers={"X-Sync-Key": app.DOK4_CURRENT_SCHEDULE_KEY},
        )
        self.assertEqual(response.status_code, 410)


if __name__ == "__main__":
    unittest.main()
