import sys
import types
import unittest


if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.jsonify = lambda value: value
    flask_stub.request = None
    sys.modules["flask"] = flask_stub

from cierny_kamen_split_0440 import (
    ACTION_0440_MD,
    augment_payload,
    scene_0440,
    split_action_0439,
)


class Split0440Tests(unittest.TestCase):
    def test_scene_is_standalone_and_complete(self):
        scene = scene_0440()
        self.assertEqual(scene["scene_id"], "04/40")
        self.assertIn("Daj mi mobil", scene["action_raw"])
        self.assertIn("Ešte raz sa pobozkajú.", scene["action_raw"])
        self.assertNotIn("Rozhovor v hudobnej", scene["action_raw"])

    def test_markdown_has_all_dialogue_speakers(self):
        self.assertIn("> **KIKO:**", ACTION_0440_MD)
        self.assertIn("> **NOEL:**", ACTION_0440_MD)

    def test_split_removes_only_embedded_segment(self):
        value = (
            "*PARALELNÉ 4/40. ETX. AMFITEÁTER – ODĽAHLÉ MIESTO, NIGHT 15 "
            "KEVIN, NOEL Kiko sa bozkáva s Noelom Alex vojde.*\n\n"
            "*Alica čaká. (prestrih) Noel zatiahol Kika na nejaké miesto v amfiku "
            "a bozká ho.*\n\n> **KIKO:**\n> Daj mi mobil.\n\n"
            "*Noel sa usmeje. (prestrih) Rozhovor v hudobnej miestnosti pokračuje. "
            "Alica príde.*"
        )
        result = split_action_0439(value)
        self.assertNotIn("Noel zatiahol", result)
        self.assertNotIn("PARALELNÉ 4/40", result)
        self.assertIn("Alex vojde", result)
        self.assertIn("Rozhovor v hudobnej miestnosti pokračuje. Alica príde", result)

    def test_augment_is_idempotent(self):
        payload = {"scenes": [{
            "scene_id": "04/39", "episode": 4, "order": 1,
            "order_in_episode": 1,
            "action_raw": (
                "PARALELNÉ 4/40. ETX. AMFITEÁTER – ODĽAHLÉ MIESTO, NIGHT 15 "
                "KEVIN, NOEL Kiko sa bozkáva s Noelom Alex. (prestrih) Noel "
                "zatiahol Kika na nejaké miesto v amfiku X (prestrih) Rozhovor "
                "v hudobnej miestnosti pokračuje. Y"
            ),
            "action_markdown": (
                "*PARALELNÉ 4/40. ETX. AMFITEÁTER – ODĽAHLÉ MIESTO, NIGHT 15 "
                "KEVIN, NOEL Kiko sa bozkáva s Noelom Alex. (prestrih) Noel "
                "zatiahol Kika na nejaké miesto v amfiku X (prestrih) Rozhovor "
                "v hudobnej miestnosti pokračuje. Y*"
            ), "props": [],
        }]}
        once = augment_payload(payload)
        twice = augment_payload(once)
        self.assertEqual(len(once["scenes"]), 2)
        self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
