import json
import sys
import types
import unittest

import extract_cierny_kamen_ep07_10 as extractor

if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.jsonify = lambda value: value
    flask_stub.request = None
    sys.modules["flask"] = flask_stub

from cierny_kamen_ep07_10_import import folded, registry_aliases


class Ep0710ImportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open("cierny_kamen_ep07_10_scenes.json", encoding="utf-8") as stream:
            cls.payload = json.load(stream)

    def test_authoritative_counts_and_ids(self):
        self.assertEqual({"07": 51, "08": 47, "09": 51, "10": 51}, self.payload["episode_counts"])
        ids = [scene["scene_id"] for scene in self.payload["scenes"]]
        self.assertEqual(200, len(ids))
        self.assertEqual(200, len(set(ids)))

    def test_0807_is_flash_only(self):
        ids = {scene["scene_id"] for scene in self.payload["scenes"]}
        self.assertIn("08/07FLASH", ids)
        self.assertNotIn("08/07", ids)
        self.assertIn("08/09", ids)

    def test_special_headings_and_locations(self):
        scenes = {scene["scene_id"]: scene for scene in self.payload["scenes"]}
        self.assertEqual("ŠKOLA – CHODBA – KUMBÁL (LIMBO)", scenes["07/04"]["location"])
        self.assertEqual("ALEX, DOGY", scenes["07/04"]["characters_raw"])
        self.assertEqual("FEFE BEEF", scenes["08/07FLASH"]["location"])
        self.assertEqual("Kiko sa bozkáva s Noelom", __import__("cierny_kamen_split_0440").scene_0440()["prepis"])

    def test_every_scene_has_verbatim_payload(self):
        for scene in self.payload["scenes"]:
            self.assertTrue(scene["prepis"], scene["scene_id"])
            self.assertTrue(scene["action_raw"], scene["scene_id"])
            self.assertEqual(64, len(scene["action_sha256"]))

    def test_parallel_scenes_are_split_and_complete(self):
        scenes = {scene["scene_id"]: scene for scene in self.payload["scenes"]}
        for scene_id in ("08/20", "09/17", "10/03LP", "10/04LP", "10/11", "10/14", "10/20"):
            self.assertNotIn(scenes[scene_id]["action_raw"].strip().casefold(), {"paralelne", "parelelne"})
            self.assertGreater(len(scenes[scene_id]["action_raw"]), 40, scene_id)
        self.assertIn("Zoberte si z chladničky", scenes["08/20"]["action_raw"])
        self.assertIn("nechal som tam mobil", scenes["08/21"]["action_raw"])
        self.assertIn("Sára, všetci čakajú", scenes["09/17"]["action_raw"])
        self.assertIn("Jakub plynulým pohybom", scenes["09/18"]["action_raw"])
        self.assertIn("Tréning tanečnej skupiny", scenes["10/04LP"]["action_raw"])
        self.assertIn("Tréning basketbalistov", scenes["10/05LP"]["action_raw"])

    def test_registry_alias_normalization(self):
        card = {"name": "ŠKOLA – KLUBOVŇA", "desc": "KANONICKÝ NÁZOV: ŠKOLA – KLUBOVŇA\nALIASY: ŠKOLA - KLUBOVŇA"}
        self.assertEqual({folded("ŠKOLA – KLUBOVŇA")}, registry_aliases(card))

    def test_explicit_identity_map_is_evidence_backed(self):
        with open("cierny_kamen_ep07_10_identity_map.json", encoding="utf-8") as stream:
            identity = json.load(stream)
        scenes = {scene["scene_id"]: scene for scene in self.payload["scenes"]}
        self.assertGreaterEqual(identity["record_count"], 180)
        for record in identity["records"]:
            self.assertIn(record["evidence_phrase"].casefold(), scenes[record["scene_id"]]["action_raw"].casefold())
            self.assertTrue(record["stable_name"])
            if record["continuity_group"]:
                self.assertTrue(record["physical_presence"])

    def test_space_map_contains_reviewed_multi_space_headings(self):
        with open("cierny_kamen_ep07_10_space_map.json", encoding="utf-8") as stream:
            spaces = json.load(stream)
        self.assertEqual(3, len(spaces["VERONIKINA VILA – VSTUP/OBÝVAČKA/JEDÁLEŇ"]))
        self.assertEqual(["ALEXOV DOM – ALEXOVA IZBA"], spaces["ALEXOV DOM – ALIXOVA IZBA"])


if __name__ == "__main__":
    unittest.main()
