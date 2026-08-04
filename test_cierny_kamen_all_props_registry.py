import sys
import types
import unittest


if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.jsonify = lambda value: value
    flask_stub.request = None
    sys.modules["flask"] = flask_stub

from cierny_kamen_all_props_registry import CATEGORY_LABELS, exact_named
from build_cierny_kamen_all_props_registry_map import (
    COMPANION_TO_RAW,
    MANUAL_ITEMS,
    categories_for_source,
    identity_core,
)


class AllPropsRegistryTests(unittest.TestCase):
    def test_required_labels_are_explicit(self):
        self.assertEqual(len(CATEGORY_LABELS), 6)
        self.assertIn("Nadväzný priestor", CATEGORY_LABELS)

    def test_exact_names_ignore_case_and_accents(self):
        values = [{"name": "REGISTER REKVIZÍT"}, {"name": "Other"}]
        self.assertEqual(exact_named(values, "register rekvizit"), [values[0]])

    def test_identity_core_removes_only_machine_suffix_and_formatting(self):
        value = (
            "<n> Betin osobný mobil — Bety číta správu | TU: nepoškodený "
            "| KARTA: https://trello.com/c/AbCd1234"
        )
        self.assertEqual(identity_core(value), "Betin osobný mobil")

    def test_every_companion_pair_points_to_an_explicit_manual_identity(self):
        self.assertTrue(all(
            raw_id is None or raw_id in MANUAL_ITEMS
            for raw_id in COMPANION_TO_RAW.values()
        ))

    def test_source_categories_are_based_on_explicit_taxonomy(self):
        record = {
            "original_stable_name": "Mobilný telefón",
            "stable_name": "Betin osobný mobil",
            "continuity_group": "betin-mobil",
        }
        self.assertEqual(
            categories_for_source(record),
            ("Nadväzná rekvizita", "Osobná rekvizita"),
        )


if __name__ == "__main__":
    unittest.main()
