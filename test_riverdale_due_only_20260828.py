import unittest
from parse_riverdale_dispo import parse
from riverdale_due_only_20260828 import date_only, due_utc


class RiverdaleDueOnlyTests(unittest.TestCase):
    def test_noon_bratislava_is_ten_utc_in_september(self):
        self.assertEqual(due_utc("2026-09-11"), "2026-09-11T10:00:00Z")

    def test_date_only(self):
        self.assertEqual(date_only("2026-09-11T10:00:00.000Z"), "2026-09-11")
        self.assertEqual(date_only(None), "")

    def test_complete_pdf_mode_includes_post_shoot_end_dates(self):
        result = parse(r"C:\Users\juraj\Desktop\plan update river 27.8.pdf", include_after_shoot_end=True)
        self.assertEqual(len(result["rows"]), 163)
        self.assertEqual(len({row["scene_id"] for row in result["rows"]}), 163)
        self.assertEqual(result["rows"][-1]["shooting_date"], "2026-10-07")


if __name__ == "__main__":
    unittest.main()
