import sys
import types
import unittest


if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.jsonify = lambda value: value
    flask_stub.request = None
    sys.modules["flask"] = flask_stub

from cierny_kamen_set_links_dedup import (
    desired_karta_suffix,
    duplicate_groups,
    find_continuity_set_item,
    find_plain_set_item,
)


class SetLinksDedupTests(unittest.TestCase):
    def test_ordinary_suffix_can_hold_multiple_space_urls(self):
        original = "BREH RIEKY + LES — prostredie obrazu 01/07"
        result = desired_karta_suffix(
            original, ["https://trello.com/c/river", "https://trello.com/c/forest"]
        )
        self.assertEqual(result.count(" | KARTA: "), 2)

    def test_continuity_suffix_replaces_ordinary_space_url(self):
        original = (
            "<n> Rozbité sklo — stav | KARTA: https://trello.com/c/space"
        )
        result = desired_karta_suffix(
            original, ["https://trello.com/c/continuity"]
        )
        self.assertNotIn("/space", result)
        self.assertTrue(result.endswith("https://trello.com/c/continuity"))

    def test_only_exact_same_text_and_state_is_duplicate(self):
        checklist = {"id": "list", "name": "REKVIZITY", "checkItems": [
            {"id": "01", "name": "same", "state": "incomplete"},
            {"id": "02", "name": "same", "state": "incomplete"},
            {"id": "03", "name": "same", "state": "complete"},
            {"id": "04", "name": "similar", "state": "incomplete"},
        ]}
        result = duplicate_groups(
            "01/08LP", {"id": "card", "shortUrl": "url"}, [checklist]
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["keep_id"], "01")
        self.assertEqual(result[0]["delete_ids"], ["02"])

    def test_environment_item_is_found_among_other_set_items(self):
        scene = {"scene_id": "01/04LP"}
        checklist = {"checkItems": [
            {"id": "car", "name": "Auto — stojí pri rieke"},
            {"id": "space", "name": "PRI RIEKE — prostredie obrazu 01/04LP"},
        ]}
        item, error = find_plain_set_item(scene, checklist)
        self.assertIsNone(error)
        self.assertEqual(item["id"], "space")

    def test_continuity_item_is_matched_by_stable_identity(self):
        scene = {"scene_id": "02/41"}
        source = {"stable_name": "Rozbité sklo automatu"}
        checklist = {"checkItems": [
            {"id": "space", "name": "KLUBOVŇA — prostredie obrazu 02/41"},
            {"id": "state", "name": "<n> Rozbité sklo automatu — stav"},
        ]}
        item, error = find_continuity_set_item(scene, source, checklist)
        self.assertIsNone(error)
        self.assertEqual(item["id"], "state")


if __name__ == "__main__":
    unittest.main()
