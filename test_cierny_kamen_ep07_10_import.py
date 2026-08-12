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

    def test_registry_alias_normalization(self):
        card = {"name": "ŠKOLA – KLUBOVŇA", "desc": "KANONICKÝ NÁZOV: ŠKOLA – KLUBOVŇA\nALIASY: ŠKOLA - KLUBOVŇA"}
        self.assertEqual({folded("ŠKOLA – KLUBOVŇA")}, registry_aliases(card))


if __name__ == "__main__":
    unittest.main()
