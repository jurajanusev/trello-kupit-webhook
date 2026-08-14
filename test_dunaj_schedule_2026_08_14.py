import json
import os
import unittest
from pathlib import Path

os.environ.setdefault("TRELLO_KEY", "test-key")
os.environ.setdefault("TRELLO_TOKEN", "test-token")

import app


ROOT = Path(__file__).parent
DOCUMENT = json.loads(
    (ROOT / "dunaj_schedule_2026-08-14.json").read_text(encoding="utf-8")
)
SOURCE_ROWS = DOCUMENT["rows"]


class DunajAugust14ScheduleTests(unittest.TestCase):
    def test_full_series_source_is_complete_and_unique(self):
        self.assertEqual(DOCUMENT["source"], app.DUNAJ_CURRENT_SOURCE_LABEL)
        self.assertEqual(len(SOURCE_ROWS), 1148)
        self.assertEqual(len({row["scene_id"] for row in SOURCE_ROWS}), 1148)
        self.assertEqual(min(row["shooting_date"] for row in SOURCE_ROWS), "2026-04-13")
        self.assertEqual(max(row["shooting_date"] for row in SOURCE_ROWS), "2026-08-21")
        self.assertTrue(all(row["location"] for row in SOURCE_ROWS))
        self.assertTrue(all(row["characters"] for row in SOURCE_ROWS))

    def test_remaining_shooting_days_and_history(self):
        dates = sorted({
            row["shooting_date"] for row in SOURCE_ROWS
            if row["shooting_date"] >= app.DUNAJ_CURRENT_SCHEDULE_AS_OF
        })[:7]
        self.assertEqual(dates, [
            "2026-08-14", "2026-08-16", "2026-08-17",
            "2026-08-20", "2026-08-21",
        ])
        self.assertEqual(
            sum(row["shooting_date"] < app.DUNAJ_CURRENT_SCHEDULE_AS_OF for row in SOURCE_ROWS),
            1090,
        )

    def test_history_and_future_have_distinct_destinations(self):
        active = ["2026-08-14", "2026-08-16", "2026-08-17", "2026-08-20", "2026-08-21"]
        self.assertEqual(app.dunaj_schedule_bucket("2026-08-13", "2026-08-14", active), "shot")
        self.assertEqual(app.dunaj_schedule_bucket("2026-08-16", "2026-08-14", active), "active")
        self.assertEqual(app.dunaj_schedule_bucket("2026-08-25", "2026-08-14", active), "series")

    def test_user_approved_aliases_and_merge_remain_stable(self):
        rows = app.canonicalize_dunaj_schedule_rows(SOURCE_ROWS)
        by_id = {row["scene_id"]: row for row in rows}
        self.assertEqual(len(rows), 1147)
        self.assertIn("23/34FLASH", by_id)
        self.assertNotIn("23/34F", by_id)
        self.assertIn("24/8", by_id)
        self.assertNotIn("24/8A", by_id)
        self.assertNotIn("24/8B", by_id)

    def test_endpoint_is_disabled_after_apply(self):
        response = app.app.test_client().post(
            "/api/sync-dunaj-schedule?mode=dry-run&as_of=2026-08-15",
            headers={"X-Sync-Key": app.DUNAJ_CURRENT_SCHEDULE_KEY},
        )
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.get_json()["error"], "endpoint disabled")


if __name__ == "__main__":
    unittest.main()
