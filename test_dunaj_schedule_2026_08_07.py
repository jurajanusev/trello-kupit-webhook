import json
import os
import unittest
from pathlib import Path

os.environ.setdefault("TRELLO_KEY", "test-key")
os.environ.setdefault("TRELLO_TOKEN", "test-token")

import app


ROOT = Path(__file__).parent
DOCUMENT = json.loads(
    (ROOT / "dunaj_schedule_2026-08-07.json").read_text(encoding="utf-8")
)
SOURCE_ROWS = DOCUMENT["rows"]


class DunajAugust7ScheduleTests(unittest.TestCase):
    def test_authoritative_json_shape(self):
        self.assertEqual(DOCUMENT["source"], "predbežná dispo DUNAJ 16 z 7. 8. 2026")
        self.assertEqual(len(SOURCE_ROWS), 108)
        self.assertEqual(len({row["scene_id"] for row in SOURCE_ROWS}), 108)
        self.assertTrue(all(row["location"] for row in SOURCE_ROWS))
        self.assertTrue(all(row["characters"] for row in SOURCE_ROWS))

    def test_next_seven_shooting_days_skip_days_off(self):
        dates = sorted({
            row["shooting_date"] for row in SOURCE_ROWS
            if row["shooting_date"] >= "2026-08-07"
        })[:7]
        self.assertEqual(dates, [
            "2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13",
            "2026-08-14", "2026-08-16", "2026-08-17",
        ])

    def test_user_approved_scene_aliases_and_merge(self):
        rows = app.canonicalize_dunaj_schedule_rows(SOURCE_ROWS)
        by_id = {row["scene_id"]: row for row in rows}
        self.assertEqual(len(rows), 107)
        self.assertIn("24/8", by_id)
        self.assertNotIn("24/8A", by_id)
        self.assertNotIn("24/8B", by_id)
        self.assertEqual(by_id["24/8"]["order_display"], "8-9")
        self.assertEqual(by_id["24/8"]["characters"], "René, Lena, Gita")

if __name__ == "__main__":
    unittest.main()
