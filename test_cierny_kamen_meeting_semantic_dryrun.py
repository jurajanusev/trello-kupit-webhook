import sys
import types
import unittest

if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.jsonify = lambda value: value
    flask_stub.request = None
    sys.modules["flask"] = flask_stub

from cierny_kamen_meeting_semantic_dryrun import (
    BANNER_SCENES, PHOTO_CONFIRMED, SCENE_0153LP_SOURCE,
    canonical_scene_id, episode_of, evidence_snippets,
)


class CiernyKamenSemanticDryRunTest(unittest.TestCase):
    def test_scope_is_only_first_three_episodes(self):
        self.assertEqual(1, episode_of("01/53LP"))
        self.assertEqual(3, episode_of("3/47C"))
        self.assertEqual(4, episode_of("04/01"))

    def test_scene_id_normalization_preserves_suffix(self):
        self.assertEqual("02/47C", canonical_scene_id("2/047c"))
        self.assertEqual("01/53LP", canonical_scene_id("01/053LP"))

    def test_source_scene_is_lp_not_plain_53(self):
        self.assertEqual("01/53LP", SCENE_0153LP_SOURCE["scene_id"])
        self.assertNotEqual("01/53", SCENE_0153LP_SOURCE["scene_id"])

    def test_banner_input_is_split_into_exact_ids(self):
        self.assertIn("02/47C", BANNER_SCENES)
        self.assertIn("02/48", BANNER_SCENES)
        self.assertNotIn("02/47C2/48", BANNER_SCENES)

    def test_photo_selection_does_not_use_every_text_hit(self):
        self.assertIn("03/15", PHOTO_CONFIRMED)
        self.assertNotIn("03/16", PHOTO_CONFIRMED)
        snippets = evidence_snippets("Bety ukáže fotku. Potom odíde.", __import__(
            "cierny_kamen_meeting_semantic_dryrun"
        ).PHOTO_RE)
        self.assertEqual(["Bety ukáže fotku."], snippets)


if __name__ == "__main__":
    unittest.main()
