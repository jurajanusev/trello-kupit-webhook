import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parent
DOCUMENT = json.loads((ROOT / "dok4_schedule_2026-08-21.json").read_text(encoding="utf-8"))
ROWS = DOCUMENT["rows"]


class Dok4August21ScheduleTests(unittest.TestCase):
    def test_source_is_unique_and_has_expected_seven_shooting_days(self):
        self.assertEqual(DOCUMENT["source"]["dated"], "2026-08-21")
        self.assertEqual(len(ROWS), 503)
        self.assertEqual(len({row["scene_id"] for row in ROWS}), 503)
        dates = sorted({row["shooting_date"] for row in ROWS if row["shooting_date"] >= "2026-08-21"})[:7]
        self.assertEqual(dates, [
            "2026-08-23", "2026-08-24", "2026-08-25", "2026-08-27",
            "2026-08-28", "2026-08-29", "2026-08-30",
        ])


if __name__ == "__main__":
    unittest.main()
