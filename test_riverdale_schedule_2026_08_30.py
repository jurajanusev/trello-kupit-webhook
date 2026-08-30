import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parent
DOCUMENT = json.loads((ROOT / "riverdale_schedule_2026-08-30.json").read_text(encoding="utf-8"))
ROWS = DOCUMENT["rows"]


class RiverdaleAugust30ScheduleTests(unittest.TestCase):
    def test_source_is_unique_and_selects_seven_shooting_days(self):
        self.assertEqual(DOCUMENT["source"]["dated"], "2026-08-30")
        self.assertEqual(len(ROWS), 140)
        self.assertEqual(len({row["scene_id"] for row in ROWS}), 140)
        dates = sorted({row["shooting_date"] for row in ROWS})[:7]
        self.assertEqual(dates, [
            "2026-09-07", "2026-09-10", "2026-09-11", "2026-09-12",
            "2026-09-13", "2026-09-15", "2026-09-16",
        ])


if __name__ == "__main__":
    unittest.main()
