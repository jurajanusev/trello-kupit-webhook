import json
import os
import unittest
from pathlib import Path

os.environ.setdefault("TRELLO_KEY", "test-key")
os.environ.setdefault("TRELLO_TOKEN", "test-token")

import app


ROOT = Path(__file__).parent
DOCUMENT = json.loads(
    (ROOT / "dunaj_schedule_2026-08-01.json").read_text(encoding="utf-8")
)
SOURCE_ROWS = DOCUMENT["rows"]


class DunajAugustScheduleTests(unittest.TestCase):
    def test_authoritative_json_shape(self):
        self.assertEqual(DOCUMENT["source"], app.DUNAJ_CURRENT_SOURCE_LABEL)
        self.assertEqual(len(SOURCE_ROWS), 152)
        self.assertEqual(len({row["scene_id"] for row in SOURCE_ROWS}), 152)

    def test_next_seven_shooting_days_skip_days_off(self):
        dates = sorted({
            row["shooting_date"] for row in SOURCE_ROWS
            if row["shooting_date"] >= app.DUNAJ_CURRENT_SCHEDULE_AS_OF
        })[:7]
        self.assertEqual(dates, [
            "2026-08-03", "2026-08-05", "2026-08-06",
            "2026-08-10", "2026-08-11", "2026-08-12",
            "2026-08-13",
        ])

    def test_user_approved_scene_aliases_and_merge(self):
        rows = app.canonicalize_dunaj_schedule_rows(SOURCE_ROWS)
        by_id = {row["scene_id"]: row for row in rows}
        self.assertEqual(len(rows), 151)
        self.assertIn("23/34FLASH", by_id)
        self.assertNotIn("23/34F", by_id)
        self.assertIn("24/8", by_id)
        self.assertNotIn("24/8A", by_id)
        self.assertNotIn("24/8B", by_id)
        self.assertEqual(by_id["24/8"]["order_display"], "8-9")
        self.assertEqual(by_id["24/8"]["characters"], "René, Lena, Gita")

    def test_completed_endpoint_is_disabled(self):
        response = app.app.test_client().post(
            "/api/sync-dunaj-schedule?as_of=2026-08-02",
            headers={"X-Sync-Key": app.DUNAJ_CURRENT_SCHEDULE_KEY},
        )
        self.assertEqual(response.status_code, 410)


if __name__ == "__main__":
    unittest.main()
