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
    bag_owner,
    contains_z,
    explicit_school_bag,
    is_production_list,
    master_block,
    starts_n,
    with_card_suffix,
)
from cierny_kamen_prop_identity_resolution import school_bag_type


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
        self.assertTrue(explicit_school_bag("Alexov školský batoh"))
        self.assertFalse(explicit_school_bag("Betin tanečný batoh"))
        self.assertEqual("bety", bag_owner("Betynina školská taška nadv. 1/21"))
        self.assertEqual("skolska taska", school_bag_type("Alexov školský batoh"))
        self.assertEqual("skolska taska", school_bag_type("Alexov batoh", school_context=True))
        self.assertIsNone(school_bag_type("Betin tanečný batoh"))

    def test_manual_n_delta_uses_last_identity_map(self):
        row = {"has_n": True}
        self.assertEqual("new_item_after_identity_map", _manual_n_status(row, None))
        self.assertEqual("n_added_after_identity_map", _manual_n_status(row, {"original_name": "**Betin mobil**"}))
        self.assertEqual("already_known_n", _manual_n_status(row, {"original_name": "<n> Betin mobil"}))

    def test_z_is_only_detected_for_protection(self):
        text = "<n> **Betin mobil** [z] | KARTA: https://trello.com/c/abc"
        self.assertTrue(starts_n(text))
        self.assertTrue(contains_z(text))

    def test_url_suffix_keeps_manual_core_verbatim(self):
        before = "<n> Alexova školská taška - nadväzný z 1/18"
        self.assertEqual(before + " | KARTA: https://trello.com/c/x", with_card_suffix(before, "https://trello.com/c/x"))

    def test_master_block_has_alias_occurrence_and_timeline(self):
        block = master_block("Alexova školská taška", [{
            "scene_id": "01/18", "scene_url": "https://trello.com/c/s",
            "text": "<n> Alexov školský batoh", "pos": 1,
        }], aliases=["Alexov školský batoh"])
        self.assertIn("ALIASY: Alexov školský batoh", block)
        self.assertIn("[01/18](https://trello.com/c/s)", block)
        self.assertIn("KATEGÓRIE: Nadväzná rekvizita", block)


if __name__ == "__main__":
    unittest.main()
