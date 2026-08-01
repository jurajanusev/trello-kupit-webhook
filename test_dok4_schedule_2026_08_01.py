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
    (ROOT / "dok4_schedule_2026-08-01.json").read_text(encoding="utf-8")
)
ROWS = DOCUMENT["rows"]


class FakeTrello:
    def __init__(self):
        self.list_id = "series-list"
        self.cards = [
            {
                "id": f"card-{index}",
                "name": f"{row['scene_id']}. Test",
                "desc": "Ručný obsah karty",
                "idList": self.list_id,
                "shortUrl": f"https://trello.com/c/card{index}",
                "due": None,
                "dueComplete": False,
                "pos": (index + 1) * 16384,
                "closed": False,
            }
            for index, row in enumerate(ROWS)
        ]

    def get(self, path, params=None):
        if path == "/boards/lzNy4AtY":
            return {
                "id": "board-id", "name": "DOK 4",
                "url": "https://trello.com/b/lzNy4AtY/dok-4",
                "shortLink": "lzNy4AtY",
            }
        if path == "/boards/board-id/lists":
            return [{
                "id": self.list_id, "name": "VŠETKY EPIZÓDY",
                "pos": 16384, "closed": False,
            }]
        if path == f"/lists/{self.list_id}/cards":
            return self.cards
        raise AssertionError((path, params))


class Dok4AugustScheduleTests(unittest.TestCase):
    def test_authoritative_json_shape(self):
        self.assertEqual(DOCUMENT["source"]["dated"], "2026-08-01")
        self.assertTrue(
            DOCUMENT["source"]["file"].endswith("plan update 1.8.pdf")
        )
        self.assertEqual(len(ROWS), 179)
        self.assertEqual(len({row["scene_id"] for row in ROWS}), 179)

    def test_next_seven_shooting_days_skip_days_off(self):
        state = build_state(
            FakeTrello(), ROWS, source_date="2026-08-01",
            as_of="2026-08-01",
        )
        report = summary(state, ROWS)
        self.assertEqual(report["board"], "DOK 4")
        self.assertEqual(report["schedule_rows"], 179)
        self.assertEqual(report["missing_count"], 0)
        self.assertEqual(report["duplicate_scene_ids_count"], 0)
        self.assertEqual(report["fallback_collision_count"], 0)
        self.assertEqual(report["shooting_dates"], [
            "2026-08-02", "2026-08-03", "2026-08-09",
            "2026-08-10", "2026-08-12", "2026-08-13",
            "2026-08-14",
        ])

    def test_completed_endpoint_is_disabled(self):
        response = app.app.test_client().post(
            "/api/sync-dok4-current-schedule?mode=dry-run&as_of=2026-08-01",
            headers={"X-Sync-Key": app.DOK4_CURRENT_SCHEDULE_KEY},
        )
        self.assertEqual(response.status_code, 410)


if __name__ == "__main__":
    unittest.main()
