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
    build_space_catalog,
    canonical_locations,
    description_without_location,
    normalize_source_location,
    parent_space,
    read_catalog_for_tests,
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


if __name__ == "__main__":
    unittest.main()
