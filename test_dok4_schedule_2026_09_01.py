import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parent
DOCUMENT = json.loads(
    (ROOT / "dok4_schedule_2026-09-01.json").read_text(encoding="utf-8")
)
ROWS = DOCUMENT["rows"]


class Dok4September1ScheduleTests(unittest.TestCase):
    def test_source_is_unique_and_selects_seven_shooting_days(self):
        self.assertEqual(DOCUMENT["source"]["dated"], "2026-09-01")
        self.assertEqual(len(ROWS), 349)
        self.assertEqual(len({row["scene_id"] for row in ROWS}), 349)
        dates = sorted({
            row["shooting_date"] for row in ROWS
            if row["shooting_date"] >= "2026-09-01"
        })[:7]
        self.assertEqual(dates, [
            "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-05",
            "2026-09-06", "2026-09-08", "2026-09-09",
        ])


if __name__ == "__main__":
    unittest.main()
