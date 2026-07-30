import json
import os
import unittest
from pathlib import Path

os.environ.setdefault("TRELLO_KEY", "test-key")
os.environ.setdefault("TRELLO_TOKEN", "test-token")

import app


ROOT = Path(__file__).parent
PAYLOAD = json.loads(
    (ROOT / "cierny_kamen_pdf_payload.json").read_text(encoding="utf-8")
)
DIFF = json.loads(
    (ROOT / "cierny_kamen_pdf_migration_diff.json").read_text(
        encoding="utf-8"
    )
)


class CiernyKamenPdfMigrationTest(unittest.TestCase):
    def setUp(self):
        self.prop_urls = {
            key: f"https://trello.com/c/prop{index}"
            for index, key in enumerate(PAYLOAD["prop_registry"])
        }
        self.set_urls = {
            key: f"https://trello.com/c/set{index}"
            for index, key in enumerate(PAYLOAD["set_registry"])
        }

    def test_pdf_payload_is_complete_and_unique(self):
        self.assertEqual(
            PAYLOAD["episode_counts"],
            {"01": 52, "02": 60, "03": 55, "04": 49, "05": 45, "06": 52},
        )
        self.assertEqual(len(PAYLOAD["scenes"]), 313)
        self.assertEqual(
            len({scene["scene_id"] for scene in PAYLOAD["scenes"]}), 313
        )
        self.assertEqual(PAYLOAD["stats"]["missing_prepis"], 0)
        self.assertEqual(PAYLOAD["stats"]["missing_action"], 0)
        self.assertEqual(
            [item["pages"] for item in PAYLOAD["source_pdfs"]],
            [92, 88, 95, 83, 81, 74],
        )
        self.assertEqual(
            [item["scenes"] for item in PAYLOAD["source_pdfs"]],
            [52, 60, 55, 49, 45, 52],
        )
        for source in PAYLOAD["source_pdfs"]:
            self.assertRegex(source["sha256"], r"^[0-9a-f]{64}$")

    def test_diff_requires_one_in_place_rename_and_episode_six(self):
        self.assertEqual(DIFF["totals"]["matched"], 261)
        self.assertEqual(DIFF["totals"]["renamed"], 1)
        self.assertEqual(DIFF["totals"]["created"], 52)
        self.assertEqual(DIFF["totals"]["removed"], 0)
        scene_ids = {scene["scene_id"] for scene in PAYLOAD["scenes"]}
        self.assertIn("01/12LP", scene_ids)
        self.assertNotIn("01/12FLASH", scene_ids)

    def test_sample_0228_uses_new_pdf_and_strict_set_rule(self):
        scene = next(
            scene for scene in PAYLOAD["scenes"]
            if scene["scene_id"] == "02/28"
        )
        description = app.cierny_kamen_scene_description(
            scene, self.prop_urls, self.set_urls
        )
        checklists = app.cierny_kamen_scene_checklists(
            scene, self.prop_urls, self.set_urls
        )
        self.assertIn(
            "ZDROJ: SC_01_02_", description
        )
        self.assertIn("_1.5_NJ_FINAL (1).pdf", description)
        self.assertIn(
            "## Kiko hovorí babám o Patrikovi a Alex hrá na gitare",
            description,
        )
        self.assertIn("> **VERONIKA:**", description)
        self.assertEqual(
            list(checklists), app.CIERNY_KAMEN_IMPORT_CHECKLISTS
        )
        self.assertEqual(len(checklists["SET"]), 4)
        self.assertTrue(
            checklists["REKVIZITY"][0].startswith(
                "<n> Alexova gitara"
            )
        )
        self.assertIn(
            "KARTA: https://trello.com/c/", checklists["REKVIZITY"][0]
        )
        self.assertIn("Nadväzná rekvizita", scene["labels"])
        self.assertNotIn("Nadväzný set", scene["labels"])
        self.assertNotIn("Auto", scene["labels"])

    def test_all_generated_content_fits_trello_and_has_no_placeholders(self):
        forbidden = ("<> ", "<N> ", "[N] ", "[n] ")
        for scene in PAYLOAD["scenes"]:
            description = app.cierny_kamen_scene_description(
                scene, self.prop_urls, self.set_urls
            )
            self.assertLess(len(description), 16384, scene["scene_id"])
            self.assertNotIn("DRYRUN-", description)
            checklists = app.cierny_kamen_scene_checklists(
                scene, self.prop_urls, self.set_urls
            )
            for items in checklists.values():
                for item in items:
                    self.assertLess(len(item), 16384, scene["scene_id"])
                    self.assertFalse(item.startswith(forbidden))
                    self.assertNotIn("KARTA: <", item)
            self.assertEqual(
                "Nadväzná rekvizita" in scene["labels"],
                any(
                    item.startswith("<n> ")
                    for item in checklists["REKVIZITY"]
                ),
            )
            self.assertEqual(
                "Nadväzný set" in scene["labels"],
                any(
                    item.startswith("<n> ")
                    for item in checklists["SET"]
                ),
            )

    def test_migration_endpoint_rejects_wrong_key_before_network(self):
        response = app.app.test_client().post(
            "/api/migrate-cierny-kamen-pdfs",
            headers={"X-PDF-Migration-Key": "wrong"},
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
