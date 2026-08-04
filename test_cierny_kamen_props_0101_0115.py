import sys
import types
import unittest


if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.jsonify = lambda value: value
    flask_stub.request = None
    sys.modules["flask"] = flask_stub

from cierny_kamen_props_0101_0115 import (
    PROP_ADDITIONS,
    QUESTION_ADDITIONS,
    SCENE_IDS,
    checklist_plan,
    exact_named,
)


class Props01010115Tests(unittest.TestCase):
    def test_scope_has_exactly_fifteen_scenes(self):
        self.assertEqual(len(SCENE_IDS), 15)
        self.assertIn("01/11FLASH", SCENE_IDS)

    def test_exact_name_is_case_and_accent_insensitive(self):
        items = [{"name": "REGISTER REKVIZÍT"}, {"name": "Other"}]
        self.assertEqual(
            exact_named(items, "register rekvizit"), [items[0]]
        )

    def test_curated_plan_is_small_and_explicit(self):
        self.assertEqual(sum(map(len, PROP_ADDITIONS.values())), 4)
        self.assertEqual(sum(map(len, QUESTION_ADDITIONS.values())), 5)

    def test_plan_preserves_existing_natural_item_and_adds_companion(self):
        checklists = [{
            "id": "props", "name": "REKVIZITY",
            "checkItems": [{"id": "manual", "name": "Kikove auto"}],
        }, {
            "id": "questions", "name": "OTÁZKY NA PORADU",
            "checkItems": [],
        }]
        plan = checklist_plan("01/15", checklists)
        self.assertEqual(len(plan), 1)
        self.assertTrue(plan[0]["name"].startswith("↳ Kikovo auto —"))
        checklists[0]["checkItems"].append({
            "id": "generated", "name": plan[0]["name"],
        })
        self.assertEqual(checklist_plan("01/15", checklists), [])


if __name__ == "__main__":
    unittest.main()
