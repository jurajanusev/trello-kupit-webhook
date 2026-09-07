import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parent
DOCUMENT = json.loads(
    (ROOT / "dunaj_schedule_2026-09-07.json").read_text(encoding="utf-8")
)
ROWS = DOCUMENT["rows"]


class DunajSeptember7ScheduleTests(unittest.TestCase):
    def test_source_is_unique_and_selects_seven_shooting_days(self):
        self.assertEqual(
            DOCUMENT["source"], "predbežná dispo DUNAJ 17 z 7. 9. 2026"
        )
        self.assertEqual(len(ROWS), 203)
        self.assertEqual(len({row["scene_id"] for row in ROWS}), 203)
        dates = sorted({
            row["shooting_date"] for row in ROWS
            if row["shooting_date"] >= "2026-09-07"
        })[:7]
        self.assertEqual(dates, [
            "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17",
            "2026-09-20", "2026-09-21", "2026-09-22",
        ])


if __name__ == "__main__":
    unittest.main()
