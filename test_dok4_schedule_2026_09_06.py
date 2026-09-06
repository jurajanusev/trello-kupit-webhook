import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parent
DOCUMENT = json.loads(
    (ROOT / "dok4_schedule_2026-09-06.json").read_text(encoding="utf-8")
)
ROWS = DOCUMENT["rows"]


class Dok4September6ScheduleTests(unittest.TestCase):
    def test_source_is_unique_and_selects_seven_shooting_days(self):
        self.assertEqual(DOCUMENT["source"]["dated"], "2026-09-06")
        self.assertEqual(len(ROWS), 827)
        self.assertEqual(len({row["scene_id"] for row in ROWS}), 827)
        dates = sorted({
            row["shooting_date"] for row in ROWS
            if row["shooting_date"] >= "2026-09-06"
        })[:7]
        self.assertEqual(dates, [
            "2026-09-06", "2026-09-08", "2026-09-09", "2026-09-13",
            "2026-09-14", "2026-09-15", "2026-09-19",
        ])


if __name__ == "__main__":
    unittest.main()
