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

    def test_identity_space_map_is_explicit_and_complete(self):
        with open("cierny_kamen_ep11_13_identity_space_map.json", encoding="utf-8") as stream:
            mapping = json.load(stream)
        ids = {row["scene_id"] for row in self.payload["scenes"]}
        self.assertEqual(ids, set(mapping["spaces_by_scene"]))
        self.assertEqual(158, mapping["space_mapping_count"])
        required = {"scene_id", "stable_name", "source_evidence", "owner", "categories",
                    "continuity_group", "current_state", "previous", "next", "ambiguity_question"}
        for row in mapping["props"]:
            self.assertEqual(required, set(row))
            self.assertTrue(row["source_evidence"])

    def test_parallel_scenes_are_not_placeholders(self):
        by_id = {row["scene_id"]: row for row in self.payload["scenes"]}
        for scene_id in ("11/01", "11/02", "11/03", "11/37", "11/39LP", "11/41",
                         "13/31", "13/32", "13/33", "13/34", "13/40", "13/45"):
            self.assertNotEqual("paralelne", by_id[scene_id]["action_raw"].strip().casefold())
            self.assertGreater(len(by_id[scene_id]["action_raw"]), 50)


if __name__ == "__main__":
    unittest.main()
