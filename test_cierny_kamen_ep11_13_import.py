import json
import unittest


class Episode1113PayloadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open("cierny_kamen_ep11_13_scenes.json", encoding="utf-8") as stream:
            cls.payload = json.load(stream)

    def test_authoritative_counts(self):
        self.assertEqual({"11": 51, "12": 52, "13": 55}, self.payload["episode_counts"])
        ids = [row["scene_id"] for row in self.payload["scenes"]]
        self.assertEqual(158, len(ids))
        self.assertEqual(158, len(set(ids)))

    def test_parallel_variants_are_separate(self):
        ids = {row["scene_id"] for row in self.payload["scenes"]}
        for scene_id in ("11/39LP", "11/40LP", "12/11FLASH", "12/47LP", "12/51LP", "13/52LP", "13/55LP"):
            self.assertIn(scene_id, ids)

    def test_every_scene_has_verbatim_source_content(self):
        for row in self.payload["scenes"]:
            self.assertTrue(row["prepis"], row["scene_id"])
            self.assertTrue(row["action_raw"], row["scene_id"])
            self.assertEqual(64, len(row["action_sha256"]))


if __name__ == "__main__":
    unittest.main()
