import unittest
from datetime import date
from shooting_props_brief import day_briefs, list_date, task_plan, START, END


class ShootingPropsBriefTests(unittest.TestCase):
    def fixture(self, text="rekvizita", checked=False):
        return ([{"id": "day", "name": "11.11."}, {"id": "todo", "name": "ToDo"}],
                [{"id": "scene", "name": "12/33. KRČMA", "idList": "day", "idChecklists": ["check"],
                  "shortUrl": "https://trello.com/c/source", "desc": "", "pos": 1},
                 {"id": "task", "name": "ToDo úloha", "idList": "todo", "desc": ""}],
                [{"id": "check", "idCard": "scene", "name": "REKVIZITY", "checkItems": [
                    {"name": text, "state": "complete" if checked else "incomplete"}]}])

    def build(self, lists=None, cards=None, checklists=None):
        a, b, c = self.fixture()
        return day_briefs("dunaj", a if lists is None else lists,
                          b if cards is None else cards, c if checklists is None else checklists,
                          date(2026, 11, 10))

    def test_reads_scheduled_scenes_without_due_and_ignores_todo(self):
        briefs = self.build()
        self.assertEqual(len(briefs), 1)
        self.assertEqual(briefs[0]["scene_count"], 1)
        self.assertIn("rekvizita", briefs[0]["body"])
        self.assertNotIn("ToDo úloha", briefs[0]["body"])

    def test_checked_props_are_still_required_and_visible(self):
        a, b, c = self.fixture(checked=True)
        brief = self.build(a, b, c)[0]
        self.assertEqual(brief["prop_count"], 1)
        self.assertIn("[zaškrtnuté v Trello] rekvizita", brief["body"])

    def test_empty_checklist_is_unknown_not_no_props(self):
        a, b, c = self.fixture()
        c[0]["checkItems"] = []
        brief = self.build(a, b, c)[0]
        self.assertTrue(brief["warnings"])
        self.assertIn("Neznamená to", brief["body"])

    def test_missing_expected_checklist_blocks_incomplete_report(self):
        with self.assertRaises(ValueError):
            self.build(checklists=[])

    def test_daily_prep_and_manual_notes_are_preserved(self):
        a, b, c = self.fixture()
        b[0]["desc"] = "## RUČNÉ DOPLNENIA\nVyrobiť duplikát.\n## AKCIA A DIALÓGY\nCelý scenár"
        b.append({"id": "prep", "idList": "day", "name": "príprava", "desc": "Objednať jedlo"})
        body = self.build(a, b, c)[0]["body"]
        self.assertIn("Vyrobiť duplikát", body)
        self.assertIn("Objednať jedlo", body)
        self.assertNotIn("Celý scenár", body)

    def test_year_rollover_and_invalid_dates(self):
        self.assertEqual(list_date("2.1.", date(2026, 12, 30)), date(2027, 1, 2))
        self.assertIsNone(list_date("31.2.", date(2026, 11, 10)))
        self.assertIsNone(list_date("NATOČENÉ OBRAZY", date(2026, 11, 10)))

    def test_long_days_are_split_without_losing_items(self):
        a, b, c = self.fixture()
        c[0]["checkItems"] = [{"name": f"unikat-{i}: " + "x" * 300, "state": "incomplete"} for i in range(150)]
        briefs = self.build(a, b, c)
        self.assertGreater(len(briefs), 1)
        self.assertTrue(all(len(brief["body"]) < 24000 for brief in briefs))
        body = "\n".join(brief["body"] for brief in briefs)
        self.assertIn("unikat-149:", body)

    def test_idempotency_completed_preservation_and_manual_notes(self):
        brief = self.build()[0]
        task = {"id": "ms", "title": brief["title"], "body": {"content": brief["body"].replace("\n", "\r\n")}}
        self.assertEqual(task_plan(brief, [task])["action"], "unchanged")
        task["body"]["content"] = "Moje poznámky\n" + brief["body"].replace("rekvizita", "stará rekvizita") + "\nDoplnené ručne"
        plan = task_plan(brief, [task])
        self.assertEqual(plan["action"], "update")
        self.assertTrue(plan["changes"]["body"]["content"].startswith("Moje poznámky"))
        self.assertTrue(plan["changes"]["body"]["content"].endswith("Doplnené ručne"))
        task["status"] = "completed"
        self.assertEqual(task_plan(brief, [task])["action"], "completed")
        with self.assertRaises(ValueError):
            task_plan(brief, [task, task])

    def test_placeholder_x_is_a_warning_not_a_prop(self):
        a, b, c = self.fixture(text="x")
        brief = self.build(a, b, c)[0]
        self.assertEqual(brief["prop_count"], 0)
        self.assertEqual(brief["unique_prop_count"], 0)
        self.assertTrue(any("nešpecifikovaná" in value for value in brief["warnings"]))


if __name__ == "__main__":
    unittest.main()
