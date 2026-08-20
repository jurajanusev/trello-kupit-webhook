import sys
import types
import unittest

if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.jsonify = lambda value: value
    flask_stub.request = None
    sys.modules["flask"] = flask_stub

from cierny_kamen_split_0535flash import ACTION_RAW, augment_payload, scene_0535flash, split_parent_action


class Split0535FlashTests(unittest.TestCase):
    def parent(self):
        return (
            "PARALELNE 5/35FLASH – PRI RIEKE – DAY X SÁRA, JAKUB Sára a Jakub sa objímajú pri odchode "
            "Sára príde k pultíku. (prestrih Flash pri rieke) Je deň, kedy sa Jakub stratil, Sára a Jakub "
            "stoja pri rieke a pozerajú si do očí. (prestrih Krematórium) Pohreb pokračuje. "
            "(prestrih Flash pri rieke) Jakub a Sára sa objímu. (prestrih Krematórium) Všetci reagujú."
        )

    def test_split_keeps_funeral_and_removes_only_flash(self):
        result = split_parent_action(self.parent())
        self.assertIn("Sára príde k pultíku", result)
        self.assertIn("Pohreb pokračuje", result)
        self.assertIn("Všetci reagujú", result)
        self.assertNotIn("Je deň, kedy sa Jakub stratil", result)
        self.assertNotIn("Jakub a Sára sa objímu", result)
        self.assertNotIn("5/35FLASH", result)

    def test_scene_has_exact_flash_only(self):
        scene = scene_0535flash()
        self.assertEqual("05/35FLASH", scene["scene_id"])
        self.assertEqual(["SÁRA", "JAKUB"], scene["characters"])
        self.assertEqual(ACTION_RAW, scene["action_raw"])
        self.assertNotIn("Krematórium", scene["action_raw"])

    def test_augment_inserts_once_between_parent_and_next(self):
        parent = {"scene_id": "05/34", "episode": 5, "order": 1, "order_in_episode": 1,
                  "action_raw": self.parent(), "action_markdown": self.parent()}
        payload = {"scenes": [parent, {"scene_id": "05/36", "episode": 5, "order": 2, "order_in_episode": 2}]}
        once = augment_payload(payload)
        twice = augment_payload(once)
        self.assertEqual(["05/34", "05/35FLASH", "05/36"], [row["scene_id"] for row in once["scenes"]])
        self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
