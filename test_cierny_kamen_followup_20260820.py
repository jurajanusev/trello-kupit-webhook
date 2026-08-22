import sys
import types
import unittest

if "flask" not in sys.modules:
    flask = types.ModuleType("flask")
    flask.jsonify = lambda value: value
    flask.request = None
    sys.modules["flask"] = flask

from cierny_kamen_followup_20260820 import (
    _manual_n_status,
    bag_type,
    contains_z,
    is_production_list,
    starts_n,
)


class FollowupTests(unittest.TestCase):
    def test_production_list_filter_excludes_non_scene_lists(self):
        self.assertTrue(is_production_list("SCENÁRE"))
        self.assertFalse(is_production_list("original screener"))
        self.assertFalse(is_production_list("BETY – OS. REKVIZITY"))
        self.assertFalse(is_production_list("REGISTER REKVIZÍT"))

    def test_school_context_backpack_is_school_bag_alias(self):
        self.assertEqual("školská taška", bag_type("**Betin batoh** | KARTA: https://trello.com/c/abc"))
        self.assertEqual("školská taška", bag_type("Kikova školská taška"))
        self.assertIsNone(bag_type("Výbava skautskej skupiny"))

    def test_manual_n_delta_uses_last_identity_map(self):
        row = {"has_n": True}
        self.assertEqual("new_item_after_identity_map", _manual_n_status(row, None))
        self.assertEqual("n_added_after_identity_map", _manual_n_status(row, {"original_name": "**Betin mobil**"}))
        self.assertEqual("already_known_n", _manual_n_status(row, {"original_name": "<n> Betin mobil"}))

    def test_z_is_only_detected_for_protection(self):
        text = "<n> **Betin mobil** [z] | KARTA: https://trello.com/c/abc"
        self.assertTrue(starts_n(text))
        self.assertTrue(contains_z(text))


if __name__ == "__main__":
    unittest.main()
