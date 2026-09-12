import json
import unittest
from pathlib import Path

from update_dok4_plan_local import date_from_list_name


ROOT = Path(__file__).parent


class September10ScheduleTests(unittest.TestCase):
    def check_plan(self, filename, rows, dates, as_of="2026-09-10"):
        document = json.loads((ROOT / filename).read_text(encoding="utf-8"))
        schedule = document["rows"]
        self.assertEqual(len(schedule), rows)
        self.assertEqual(len({row["scene_id"] for row in schedule}), rows)
        selected = sorted({
            row["shooting_date"] for row in schedule
            if row["shooting_date"] >= as_of
        })[:7]
        self.assertEqual(selected, dates)

    def test_dunaj(self):
        self.check_plan("dunaj_schedule_2026-09-10.json", 203, [
            "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17",
            "2026-09-20", "2026-09-21", "2026-09-22",
        ])

    def test_riverdale(self):
        self.check_plan("riverdale_schedule_2026-09-10.json", 136, [
            "2026-09-10", "2026-09-11", "2026-09-12", "2026-09-13",
            "2026-09-15", "2026-09-16", "2026-09-18",
        ])
        self.assertEqual(date_from_list_name("10.9."), "2026-09-10")

    def test_dok4(self):
        self.check_plan("dok4_schedule_2026-09-10.json", 827, [
            "2026-09-13", "2026-09-14", "2026-09-15", "2026-09-19",
            "2026-09-20", "2026-09-21", "2026-09-22",
        ])

    def test_riverdale_september_12(self):
        self.check_plan("riverdale_schedule_2026-09-12.json", 125, [
            "2026-09-12", "2026-09-13", "2026-09-15", "2026-09-16",
            "2026-09-20", "2026-09-22", "2026-09-24",
        ], as_of="2026-09-12")


if __name__ == "__main__":
    unittest.main()
