import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parent
DOCUMENT = json.loads((ROOT / "riverdale_schedule_2026-08-22.json").read_text(encoding="utf-8"))
ROWS = DOCUMENT["rows"]


class RiverdaleAugust22ScheduleTests(unittest.TestCase):
    def test_explicit_day_dates_and_seven_shooting_day_window(self):
        self.assertEqual(DOCUMENT["source"]["dated"], "2026-08-22")
        self.assertEqual(DOCUMENT["source"]["date_derivation"],
                         "Explicit date from each numbered Day header.")
        self.assertEqual(len(ROWS), 140)
        self.assertEqual(len({row["scene_id"] for row in ROWS}), 140)
        dates = sorted({row["shooting_date"] for row in ROWS})[:7]
        self.assertEqual(dates, [
            "2026-09-07", "2026-09-10", "2026-09-11", "2026-09-12",
            "2026-09-13", "2026-09-14", "2026-09-16",
        ])

    def test_five_column_layout_preserves_location_story_and_characters(self):
        first = ROWS[0]
        self.assertEqual(first["scene_id"], "01/13")
        self.assertEqual(first["location"], "PRED VERONIKINOU VILOU")
        self.assertIn("Veronika", first["story"])
        self.assertIn("Laura", first["characters"])


if __name__ == "__main__":
    unittest.main()
