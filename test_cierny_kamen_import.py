import json
import os
import unittest
from pathlib import Path

os.environ.setdefault("TRELLO_KEY", "test-key")
os.environ.setdefault("TRELLO_TOKEN", "test-token")

import app


PAYLOAD = json.loads(
    Path(__file__).with_name("cierny_kamen_import_payload.json").read_text(
        encoding="utf-8"
    )
)


class CiernyKamenPayloadTest(unittest.TestCase):
    def setUp(self):
        self.prop_urls = {
            key: f"https://trello.com/c/prop{index}"
            for index, key in enumerate(PAYLOAD["prop_registry"])
        }
        self.set_urls = {
            key: f"https://trello.com/c/set{index}"
            for index, key in enumerate(PAYLOAD["set_registry"])
        }

    def test_source_counts_and_required_content_are_complete(self):
        self.assertEqual(PAYLOAD["episode_counts"], {
            "01": 52, "02": 60, "03": 55, "04": 49, "05": 45,
        })
        self.assertEqual(len(PAYLOAD["scenes"]), 261)
        self.assertEqual(
            len({scene["scene_id"] for scene in PAYLOAD["scenes"]}), 261
        )
        self.assertEqual(PAYLOAD["stats"]["missing_prepis"], 0)
        self.assertEqual(PAYLOAD["stats"]["missing_action"], 0)
        self.assertEqual(PAYLOAD["stats"]["set_items_total"], 267)
        self.assertEqual(PAYLOAD["stats"]["strict_set_chains"], 5)
        self.assertEqual(PAYLOAD["stats"]["continuity_set_scenes"], 29)

    def test_sample_0228_matches_required_structure(self):
        scene = next(
            scene for scene in PAYLOAD["scenes"]
            if scene["scene_id"] == "02/28"
        )
        self.assertEqual(
            scene["prepis"],
            "Kiko hovorí babám o Patrikovi a Alex hrá na gitare",
        )
        description = app.cierny_kamen_scene_description(
            scene, self.prop_urls, self.set_urls
        )
        headings = [
            description.index("<!-- CIERNY-KAMEN-SCHEDULE-METADATA:START -->"),
            description.index("## Kiko hovorí babám"),
            description.index("### REKVIZITY V KONTEXTE"),
            description.index("### KONTINUITA"),
            description.index("### ODKAZY"),
            description.index("### RUČNÉ DOPLNENIA"),
            description.index("### AKCIA A DIALÓGY"),
        ]
        self.assertEqual(headings, sorted(headings))
        self.assertNotIn("ORIGINÁLNY SCENÁR", description)
        self.assertIn(
            "> **VERONIKA:**\n> Čo od teba chcel Patrik?",
            description,
        )
        checklists = app.cierny_kamen_scene_checklists(
            scene, self.prop_urls, self.set_urls
        )
        self.assertEqual(list(checklists), app.CIERNY_KAMEN_IMPORT_CHECKLISTS)
        self.assertEqual(len(checklists["REKVIZITY"]), 1)
        self.assertEqual(len(checklists["SET"]), 4)
        self.assertNotIn("Nadväzný set", scene["labels"])
        self.assertFalse(
            any(item.startswith("<n> ") for item in checklists["SET"])
        )
        prop = checklists["REKVIZITY"][0]
        self.assertTrue(prop.startswith("<n> Alexova gitara — "))
        self.assertIn("| ← 01/39: Alex na nej hrá na terase |", prop)
        self.assertIn(
            "| TU: gitara je funkčná a nepoškodená; "
            "overiť rovnaký konkrétny kus, farbu a popruh |",
            prop,
        )
        self.assertIn("| KARTA: https://trello.com/c/", prop)
        self.assertEqual(checklists["INFO Z PORADY"], [])
        self.assertEqual(checklists["INFO Z NATÁČANIA"], [])
        self.assertEqual(checklists["OTÁZKY NA PORADU"], [])

    def test_all_card_descriptions_and_checklist_items_fit_trello_limits(self):
        longest_description = 0
        longest_item = 0
        for scene in PAYLOAD["scenes"]:
            description = app.cierny_kamen_scene_description(
                scene, self.prop_urls, self.set_urls
            )
            longest_description = max(longest_description, len(description))
            checklists = app.cierny_kamen_scene_checklists(
                scene, self.prop_urls, self.set_urls
            )
            for items in checklists.values():
                for item in items:
                    longest_item = max(longest_item, len(item))
                    self.assertNotIn("KARTA: <", item)
        self.assertLess(longest_description, 16384)
        self.assertLess(longest_item, 16384)

    def test_all_continuity_items_use_only_lowercase_n_marker(self):
        forbidden = ("<> ", "<N> ", "[N] ", "[n] ")
        continuity_items = 0
        for scene in PAYLOAD["scenes"]:
            checklists = app.cierny_kamen_scene_checklists(
                scene, self.prop_urls, self.set_urls
            )
            prop_items = checklists["REKVIZITY"]
            set_items = checklists["SET"]
            for item in prop_items + set_items:
                self.assertFalse(item.startswith(forbidden))
                if app.cierny_kamen_continuity_prefix_parts(item):
                    continuity_items += 1
                    self.assertTrue(item.startswith("<n> "))
            self.assertEqual(
                "Nadväzná rekvizita" in scene["labels"],
                any(item.startswith("<n> ") for item in prop_items),
            )
            self.assertEqual(
                "Nadväzný set" in scene["labels"],
                any(item.startswith("<n> ") for item in set_items),
            )
        self.assertGreater(continuity_items, 0)

    def test_marker_parser_recognizes_legacy_variants_but_only_lowercase_is_valid(self):
        cases = {
            "<n> Gitara": True,
            "<> Gitara": False,
            "<N> Gitara": False,
            "[N] Gitara": False,
            "[n] Gitara": False,
        }
        for value, valid in cases.items():
            with self.subTest(value=value):
                parsed = app.cierny_kamen_continuity_prefix_parts(value)
                self.assertIsNotNone(parsed)
                self.assertEqual(parsed["valid"], valid)
                self.assertEqual(parsed["suffix"], "Gitara")

    def test_registry_descriptions_use_only_real_or_pending_scene_links(self):
        scene_urls = {
            scene["scene_id"]: f"https://trello.com/c/scene{index}"
            for index, scene in enumerate(PAYLOAD["scenes"])
        }
        for kind, entries in (
            ("PROP", PAYLOAD["prop_registry"]),
            ("SET", PAYLOAD["set_registry"]),
        ):
            for key, entry in entries.items():
                description = app.cierny_kamen_registry_description(
                    kind, key, entry, scene_urls
                )
                self.assertIn("https://trello.com/c/", description)
                self.assertNotIn("karta obrazu zatiaľ", description)
                self.assertLess(len(description), 16384)

    def test_completed_import_endpoint_is_gone(self):
        response = app.app.test_client().post(
            "/api/import-cierny-kamen",
            headers={"X-Import-Key": app.CIERNY_KAMEN_IMPORT_KEY},
        )
        self.assertEqual(response.status_code, 410)
        self.assertEqual(
            response.json["error"], "completed import endpoint disabled"
        )

    def test_set_fix_preserves_manual_description_text(self):
        actual = (
            "x\n### RUČNÉ DOPLNENIA\nručná poznámka\n"
            "### AKCIA A DIALÓGY\npôvodná akcia"
        )
        desired = (
            "y\n### RUČNÉ DOPLNENIA\n\n"
            "### AKCIA A DIALÓGY\nnová akcia"
        )
        merged = app.cierny_kamen_preserve_manual_description(
            actual, desired
        )
        self.assertIn(
            "### RUČNÉ DOPLNENIA\nručná poznámka\n"
            "### AKCIA A DIALÓGY",
            merged,
        )
        self.assertTrue(merged.endswith("nová akcia"))

    def test_completed_set_fix_endpoint_is_gone(self):
        response = app.app.test_client().post(
            "/api/fix-cierny-kamen-set-continuity",
            headers={"X-Fix-Key": app.CIERNY_KAMEN_SET_FIX_KEY},
        )
        self.assertEqual(response.status_code, 410)
        self.assertEqual(
            response.json["error"], "completed SET fix endpoint disabled"
        )


if __name__ == "__main__":
    unittest.main()
