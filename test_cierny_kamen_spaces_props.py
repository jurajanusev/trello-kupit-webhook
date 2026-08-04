import unittest
import sys
import types
from datetime import timezone


if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.jsonify = lambda value: value
    flask_stub.request = None
    sys.modules["flask"] = flask_stub

from cierny_kamen_spaces_props import (
    CURATED_PROP_ACTIONS,
    POLICE_BOAT_NAME,
    build_space_catalog,
    canonical_locations,
    description_without_location,
    is_automatic_natural_prop_item,
    normalize_source_location,
    original_checklist_projection,
    parent_space,
    projection_is_preserved,
    read_catalog_for_tests,
    replace_location_value,
    trello_object_created_at,
)


class SpaceMappingTests(unittest.TestCase):
    def test_dash_variants_share_identity(self):
        self.assertEqual(
            canonical_locations("DOM BETY - IZBA BETY"),
            ("DOM BETY – IZBA BETY",),
        )

    def test_reviewed_multi_space_is_split(self):
        self.assertEqual(
            canonical_locations("BREH RIEKY + LES"),
            ("BREH RIEKY", "LES"),
        )

    def test_day_night_identity_is_not_split(self):
        self.assertEqual(
            canonical_locations("KOLÁŽ STOCKSHOTOV – DAY/NIGHT"),
            ("KOLÁŽ STOCKSHOTOV – DAY/NIGHT",),
        )

    def test_schedule_suffix_is_removed(self):
        self.assertEqual(
            normalize_source_location("ŠKOLA – CHODBA SO SKRINKAMI - DAY Y"),
            "ŠKOLA – CHODBA SO SKRINKAMI",
        )

    def test_parent_is_only_explicit_story_parent(self):
        self.assertEqual(parent_space("ŠKOLA – KLUBOVŇA"), "ŠKOLA")
        self.assertIsNone(parent_space("NA RIEKE – ČLN"))

    def test_location_only_normalization_protects_rest_of_description(self):
        before = (
            "prefix\n<!-- CIERNY-KAMEN-SCHEDULE-METADATA:START -->\n"
            "ČÍSLO OBRAZU: 02/28\nLOKÁCIA: ŠKOLA – KLUBOVŇA\n"
            "POSTAVY: ALEX\n<!-- CIERNY-KAMEN-SCHEDULE-METADATA:END -->"
            "\nmanual and dialogue"
        )
        after = before.replace(
            "LOKÁCIA: ŠKOLA – KLUBOVŇA",
            "LOKÁCIA: [ŠKOLA – KLUBOVŇA](https://trello.com/c/test)",
        )
        self.assertEqual(
            description_without_location(before),
            description_without_location(after),
        )

    def test_replace_location_changes_only_location_value(self):
        before = (
            "<!-- CIERNY-KAMEN-SCHEDULE-METADATA:START -->\n"
            "ČÍSLO OBRAZU: 01/16\nLOKÁCIA: DOM BETY – IZBA BETY\n"
            "POSTAVY: BETY, KIKO\n"
            "<!-- CIERNY-KAMEN-SCHEDULE-METADATA:END -->\nmanual"
        )
        after = replace_location_value(
            before,
            "[DOM BETY – IZBA BETY](https://trello.com/c/space)",
        )
        self.assertIn("LOKÁCIA: [DOM BETY", after)
        self.assertEqual(
            description_without_location(before),
            description_without_location(after),
        )

    def test_original_checklist_items_may_only_be_extended(self):
        before_lists = [{
            "id": "check", "name": "REKVIZITY", "pos": 1,
            "checkItems": [{
                "id": "manual", "name": "Alicin mobil",
                "state": "incomplete", "pos": 1,
            }],
        }]
        before = original_checklist_projection(before_lists)
        after = [{
            **before_lists[0],
            "checkItems": before_lists[0]["checkItems"] + [{
                "id": "auto", "name": "↳ kontext", "state": "incomplete",
                "pos": 2,
            }],
        }]
        self.assertTrue(projection_is_preserved(before, after))
        after[0]["checkItems"][0]["name"] = "renamed"
        self.assertFalse(projection_is_preserved(before, after))

    def test_authoritative_payload_has_313_scenes(self):
        catalog = read_catalog_for_tests()
        matched = sum(bool(value) for value in catalog["scene_locations"].values())
        self.assertEqual(len(catalog["scene_locations"]), 313)
        self.assertEqual(matched + len(catalog["ambiguous"]), 313)
        self.assertFalse(catalog["key_collisions"])

    def test_trello_object_id_timestamp_is_deterministic(self):
        created = trello_object_created_at("6a71945fbc40caec67ceb03a")
        self.assertEqual(created.tzinfo, timezone.utc)
        self.assertEqual(created.isoformat(), "2026-08-04T07:27:27+00:00")

    def test_all_new_manual_prop_items_have_explicit_curation(self):
        self.assertEqual(len(CURATED_PROP_ACTIONS), 17)
        self.assertTrue(all(len(item_id) == 24 for item_id in CURATED_PROP_ACTIONS))
        self.assertTrue(all(
            set(action).intersection({"companion", "question", "continuity"})
            for action in CURATED_PROP_ACTIONS.values()
        ))

    def test_only_reviewed_police_boat_creates_continuity(self):
        continuity = [
            action["continuity"]
            for action in CURATED_PROP_ACTIONS.values()
            if action.get("continuity")
        ]
        self.assertEqual(continuity, ["police_boat"])
        self.assertNotIn("<n>", POLICE_BOAT_NAME)

    def test_only_exact_automatic_items_are_excluded_from_manual_scan(self):
        self.assertTrue(is_automatic_natural_prop_item("↳ automatic context"))
        self.assertTrue(is_automatic_natural_prop_item(
            f"<n> {POLICE_BOAT_NAME} — action | KARTA: https://trello.com/c/abc"
        ))
        self.assertFalse(is_automatic_natural_prop_item("<n> Sarina šatka"))
        self.assertFalse(is_automatic_natural_prop_item("Alicin mobil"))


if __name__ == "__main__":
    unittest.main()
