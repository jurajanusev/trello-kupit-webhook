import sys
import types
import unittest
import json
from pathlib import Path


if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.jsonify = lambda value: value
    flask_stub.request = None
    sys.modules["flask"] = flask_stub

from cierny_kamen_all_props_registry import (
    CATEGORY_LABELS,
    PROP_AUTO_END,
    PROP_AUTO_START,
    SAMPLE_IDENTITIES,
    alias_core,
    exact_named,
    outside_auto_block,
    replace_auto_block,
    with_card_suffix,
)
from build_cierny_kamen_all_props_registry_map import (
    COMPANION_TO_RAW,
    MANUAL_ITEMS,
    categories_for_source,
    identity_core,
)
from cierny_kamen_prop_identities import apply_identity_map


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

    def test_suffix_update_preserves_manual_core(self):
        original = "Alicin mobil — ručný kontext | TU: nepoškodený"
        linked = with_card_suffix(original, "https://trello.com/c/AbCd1234")
        updated = with_card_suffix(linked, "https://trello.com/c/ZyXw9876")
        self.assertEqual(
            updated,
            original + " | KARTA: https://trello.com/c/ZyXw9876",
        )

    def test_auto_block_replacement_preserves_manual_text(self):
        old = f"ručný úvod\n\n{PROP_AUTO_START}\nold\n{PROP_AUTO_END}\nručný koniec"
        new_block = f"{PROP_AUTO_START}\nnew\n{PROP_AUTO_END}"
        updated = replace_auto_block(old, new_block)
        self.assertEqual(outside_auto_block(old), outside_auto_block(updated))
        self.assertIn("new", updated)
        self.assertNotIn("\nold\n", updated)

    def test_alias_core_drops_formatting_not_identity(self):
        self.assertEqual(
            alias_core("<n> Betin mobil — ručný stav | KARTA: https://trello.com/c/Ab1"),
            "Betin mobil",
        )

    def test_sample_covers_five_explicit_identities(self):
        self.assertEqual(len(SAMPLE_IDENTITIES), 5)

    def test_future_payload_registers_every_included_prop(self):
        raw = json.loads(
            Path("cierny_kamen_pdf_payload.json").read_text(encoding="utf-8")
        )
        mapped = apply_identity_map(raw)
        props = [item for scene in mapped["scenes"] for item in scene["props"]]
        self.assertEqual(len(props), 195)
        self.assertTrue(all(item.get("registry_key") for item in props))
        self.assertEqual(len(mapped["prop_registry"]), 137)
        self.assertTrue(all(
            "categories" in entry and "continuity" in entry
            for entry in mapped["prop_registry"].values()
        ))


if __name__ == "__main__":
    unittest.main()
