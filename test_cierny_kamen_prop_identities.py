import copy
import json
import os
import re
import unittest
from pathlib import Path

os.environ.setdefault("TRELLO_KEY", "test-key")
os.environ.setdefault("TRELLO_TOKEN", "test-token")

import app
from cierny_kamen_prop_identities import apply_identity_map, load_identity_map
from cierny_kamen_prop_identity_repair import PropRepair


ROOT = Path(__file__).parent
RAW = json.loads(
    (ROOT / "cierny_kamen_pdf_payload.json").read_text(encoding="utf-8")
)
MAPPED = apply_identity_map(RAW)
MAP = load_identity_map()

FORBIDDEN = {
    "Mobilný telefón", "Auto / vozidlo", "Notebook / laptop",
    "Fotografie / fotoalbum", "Jedlo / nápoj", "Taška / batoh",
    "Peniaze / bankovky", "Pištoľ / zbraň", "Bunda",
    "Dokumenty / zmluva / spis", "Kamera", "Kvety", "Denník",
    "Kufor", "Obálka", "Kľúče", "Diktafón", "Plyšová hračka",
    "Slúchadlá", "Blister s liekmi / Ritalin",
}


class PropIdentityMapTests(unittest.TestCase):
    def test_exactly_all_225_current_items_are_reviewed(self):
        self.assertEqual(MAP["reviewed_current_items"], 225)
        self.assertEqual(len(MAP["records"]), 225)
        self.assertEqual(
            len({record["record_id"] for record in MAP["records"]}), 225
        )
        self.assertEqual(
            sum(len(scene["props"]) for scene in RAW["scenes"]), 225
        )

    def test_no_included_generic_identity(self):
        included = [r for r in MAP["records"] if r["include"]]
        self.assertFalse(
            [(r["record_id"], r["stable_name"]) for r in included
             if r["stable_name"] in FORBIDDEN]
        )
        for record in included:
            self.assertNotIn("/", record["stable_name"])
            self.assertNotRegex(record["stable_name"], r"^\s*(?:mobil|auto|notebook|laptop|fotografi|jedlo|nápoj|taška|batoh|peniaze|bankovky|pištoľ|zbraň|bunda|dokumenty|kamera|kvety|denník|kufor|obálka|kľúče|diktafón|slúchadlá)\s*$",)

    def test_continuity_is_physical_specific_and_unambiguous(self):
        for record in MAP["records"]:
            if record["continuity_group"]:
                self.assertTrue(record["include"])
                self.assertTrue(record["physical_presence"])
                self.assertEqual(record["evidence_kind"], "physical")
                self.assertIsNone(record["ambiguity_question"])
                self.assertNotIn(record["stable_name"], FORBIDDEN)
                self.assertTrue(record["previous"])
                self.assertTrue(record["next"])
            if record["evidence_kind"] != "physical":
                self.assertIsNone(record["continuity_group"])
            if record["ambiguity_question"]:
                self.assertIsNone(record["continuity_group"])

    def test_one_stable_identity_per_continuity_group(self):
        groups = {}
        for record in MAP["records"]:
            if record["continuity_group"]:
                groups.setdefault(record["continuity_group"], set()).add(
                    record["stable_name"]
                )
        self.assertTrue(groups)
        self.assertFalse(
            {key: names for key, names in groups.items() if len(names) != 1}
        )

    def test_generated_continuity_items_have_real_url_shape(self):
        prop_urls = {
            key: f"https://trello.com/c/TEST-{index:03d}"
            for index, key in enumerate(MAPPED["prop_registry"])
        }
        set_urls = {
            key: f"https://trello.com/c/SET-{index:03d}"
            for index, key in enumerate(MAPPED["set_registry"])
        }
        for scene in MAPPED["scenes"]:
            items = app.cierny_kamen_scene_checklists(
                scene, prop_urls, set_urls
            )["REKVIZITY"]
            for item in items:
                if item.startswith("<n>"):
                    self.assertRegex(
                        item, r"\| KARTA: https://trello\.com/c/[A-Za-z0-9-]+$"
                    )
                    self.assertIn(" | ← ", item)
                    self.assertIn(" | TU: ", item)
                    self.assertIn(" | → ", item)

    def test_questions_are_materialized(self):
        by_scene = {scene["scene_id"]: scene for scene in MAPPED["scenes"]}
        for record in MAP["records"]:
            if record["ambiguity_question"]:
                self.assertIn(
                    record["ambiguity_question"],
                    by_scene[record["scene_id"]]["questions"],
                )

    def test_required_high_risk_splits(self):
        by_id = {r["record_id"]: r for r in MAP["records"]}
        self.assertFalse(by_id["01/32FLASH#0"]["include"])
        self.assertIsNone(by_id["01/19#0"]["continuity_group"])
        self.assertIsNone(by_id["03/47LP#0"]["continuity_group"])
        self.assertEqual(
            by_id["04/47LP#0"]["continuity_group"], "betin-novy-dennik"
        )
        self.assertNotEqual(
            by_id["04/06LP#0"]["continuity_group"],
            by_id["04/47LP#0"]["continuity_group"],
        )
        self.assertFalse(by_id["01/17#0"]["include"])
        self.assertFalse(by_id["05/20#0"]["include"])
        self.assertFalse(by_id["06/43#0"]["include"])

    def test_scene_count_and_ids_unchanged(self):
        self.assertEqual(len(MAPPED["scenes"]), 313)
        self.assertEqual(
            {s["scene_id"] for s in MAPPED["scenes"]},
            {s["scene_id"] for s in RAW["scenes"]},
        )

    def test_description_repair_preserves_every_out_of_scope_section(self):
        repair = PropRepair({"__file__": str(ROOT / "app.py")})
        actual = (
            "METADATA\n\n### REKVIZITY V KONTEXTE\nOLD PROPS\n\n"
            "### KONTINUITA\nOLD CONT\n\n### ODKAZY\nOLD LINKS\n\n"
            "### RUČNÉ DOPLNENIA\nMANUAL\n\n### AKCIA A DIALÓGY\nVERBATIM"
        )
        desired = (
            "CHANGED METADATA\n\n### REKVIZITY V KONTEXTE\nNEW PROPS\n\n"
            "### KONTINUITA\nNEW CONT\n\n### ODKAZY\nNEW LINKS\n\n"
            "### RUČNÉ DOPLNENIA\nSHOULD NOT REPLACE\n\n"
            "### AKCIA A DIALÓGY\nSHOULD NOT REPLACE"
        )
        result = repair.replace_prop_sections(actual, desired)
        self.assertTrue(result.startswith("METADATA\n"))
        self.assertIn("NEW PROPS", result)
        self.assertIn("NEW CONT", result)
        self.assertIn("NEW LINKS", result)
        self.assertIn("### RUČNÉ DOPLNENIA\nMANUAL", result)
        self.assertTrue(result.endswith("### AKCIA A DIALÓGY\nVERBATIM"))

    def test_registry_marker_discovery_uses_production_marker_shape(self):
        repair = PropRepair({"__file__": str(ROOT / "app.py")})
        card = {
            "id": "card-1", "closed": False,
            "desc": "<!-- CIERNY-KAMEN-REGISTRY:PROP:alexova-gitara -->",
        }
        self.assertEqual(
            repair.marker_cards({"cards": [card]}, "PROP"),
            {"alexova-gitara": [card]},
        )

    def test_completed_repair_endpoint_is_disabled(self):
        response = app.app.test_client().post(
            "/api/repair-cierny-kamen-prop-identities",
            headers={"X-Prop-Identity-Key": "irrelevant"},
        )
        self.assertEqual(response.status_code, 410)


if __name__ == "__main__":
    unittest.main()
