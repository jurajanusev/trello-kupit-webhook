import unittest
from parse_riverdale_dispo import parse
from riverdale_due_only_20260828 import date_only, due_utc, microsoft_due_date, microsoft_due_report


class RiverdaleDueOnlyTests(unittest.TestCase):
    def test_noon_bratislava_is_ten_utc_in_september(self):
        self.assertEqual(due_utc("2026-09-11"), "2026-09-11T10:00:00Z")

    def test_date_only(self):
        self.assertEqual(date_only("2026-09-11T10:00:00.000Z"), "2026-09-11")
        self.assertEqual(date_only(None), "")

    def test_microsoft_utc_due_is_compared_in_bratislava(self):
        task = {"dueDateTime": {"dateTime": "2026-09-06T22:00:00.0000000", "timeZone": "UTC"}}
        self.assertEqual(microsoft_due_date(task), "2026-09-07")

    def test_complete_pdf_mode_includes_post_shoot_end_dates(self):
        result = parse(r"C:\Users\juraj\Desktop\plan update river 27.8.pdf", include_after_shoot_end=True)
        self.assertEqual(len(result["rows"]), 163)
        self.assertEqual(len({row["scene_id"] for row in result["rows"]}), 163)
        self.assertEqual(result["rows"][-1]["shooting_date"], "2026-10-07")

    def test_microsoft_due_report_never_plans_creates(self):
        card = {"name": "Known", "shortUrl": "https://trello.com/c/known", "due": "2026-09-11T10:00:00Z"}
        missing = {"name": "Missing", "shortUrl": "https://trello.com/c/missing", "due": "2026-09-12T10:00:00Z"}

        def trello_get(path, params):
            if path.endswith("/lists"):
                return [{"id": "todo", "name": "ToDo"}]
            return [card, missing]

        api = {
            "trello_get": trello_get,
            "get_microsoft_access_token": lambda: "token",
            "graph_get_all": lambda path, token: [{
                "id": "task", "title": "Known", "body": {"content": card["shortUrl"]},
                "dueDateTime": {"dateTime": "2026-09-10T12:00:00"},
            }],
            "TODO_LIST_ID": "list",
        }
        token, plans, absent, conflicts = microsoft_due_report(api)
        self.assertEqual(token, "token")
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["desired_due"], "2026-09-11")
        self.assertEqual([item["name"] for item in absent], ["Missing"])
        self.assertEqual(conflicts, [])


if __name__ == "__main__":
    unittest.main()
