import sys
import types
import unittest

if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.jsonify = lambda value: value
    flask_stub.request = None
    sys.modules["flask"] = flask_stub

from cierny_kamen_meeting_semantic_apply import (
    BANNER_SCENES, SAFE_PROP_NOTES, SAFE_SET_NOTES, _scene_item,
)
from cierny_kamen_meeting_semantic_dryrun import vehicles_plan


class SemanticApplyTest(unittest.TestCase):
    def test_eclipse_is_scoped_to_dance_group_context(self):
        self.assertIn("02/46", SAFE_SET_NOTES)
        self.assertIn("02/47A", SAFE_SET_NOTES)
        self.assertTrue(any("ECLIPSE" in row for row in SAFE_SET_NOTES["02/46"]))

    def test_pitevna_item_is_defined_for_continuity_master(self):
        from cierny_kamen_meeting_semantic_apply import SET_MASTER_ITEMS
        self.assertEqual(["Podsvetľovací box na röntgen"], SET_MASTER_ITEMS["PITEVŇA"])

    def test_negative_presence_notes_are_not_created_as_props(self):
        flat = "\n".join(value for rows in SAFE_PROP_NOTES.values() for value in rows).casefold()
        self.assertNotIn("auto nevidíme", flat)
        self.assertNotIn("nie je tu", flat)

    def test_linked_item_markdown_keeps_url_outside_italic(self):
        row = _scene_item("Doggyho slúchadlá", "https://trello.com/c/test", "fyzicky ich má", "01/01", "01/03", True)
        self.assertTrue(row.startswith("<n> **Doggyho slúchadlá**"))
        self.assertIn("* | KARTA: https://trello.com/c/test", row)
        self.assertEqual(6, row.count("*"))

    def test_banner_exact_scene_set_is_preserved(self):
        self.assertEqual(8, len(BANNER_SCENES))
        self.assertIn("02/47C", BANNER_SCENES)
        self.assertIn("02/48", BANNER_SCENES)

    def test_generic_van_is_not_a_safe_vehicle_move(self):
        state = {
            "labels": [{"id": "auto", "name": "Auto"}],
            "open_lists": [],
            "cards": [{
                "id": "van", "name": "DODÁVKA - REKVI", "desc": "01/09",
                "shortUrl": "https://trello.com/c/van", "list_name": "REGISTER REKVIZÍT",
                "idLabels": ["auto"], "checklists": [], "closed": False,
            }],
        }
        plan = vehicles_plan(state)
        self.assertEqual(0, plan["confirmed_master_count"])
        self.assertEqual(1, len(plan["blocked_semantic_conflict_groups"]))


if __name__ == "__main__":
    unittest.main()
