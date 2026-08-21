import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parent
DOCUMENT = json.loads((ROOT / "riverdale_schedule_2026-08-21.json").read_text(encoding="utf-8"))
ROWS = DOCUMENT["rows"]


class RiverdaleAugust21ScheduleTests(unittest.TestCase):
    def test_source_is_unique_and_has_expected_seven_shooting_days(self):
        self.assertEqual(DOCUMENT["source"]["dated"], "2026-08-21")
        self.assertEqual(len(ROWS), 142)
        self.assertEqual(len({row["scene_id"] for row in ROWS}), 142)
        dates = sorted({row["shooting_date"] for row in ROWS if row["shooting_date"] >= "2026-08-21"})[:7]
        self.assertEqual(dates, [
            "2026-08-21", "2026-08-24", "2026-08-25", "2026-08-26",
            "2026-08-27", "2026-08-28", "2026-08-30",
        ])

    def test_day_off_rows_advance_calendar_without_consuming_shooting_day(self):
        by_day = {}
        for row in ROWS:
            by_day.setdefault(row["shooting_day"], row["shooting_date"])
        self.assertEqual(by_day[1], "2026-08-21")
        self.assertEqual(by_day[2], "2026-08-24")
        self.assertEqual(by_day[7], "2026-08-30")


if __name__ == "__main__":
    unittest.main()
