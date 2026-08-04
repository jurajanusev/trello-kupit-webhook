import sys
import types
import unittest


if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.jsonify = lambda value: value
    flask_stub.request = None
    sys.modules["flask"] = flask_stub

from cierny_kamen_reference_all import same_story_space, story_space_key
from cierny_kamen_reference_0116 import (
    METADATA_END, METADATA_START, parse_description,
)


class AllReferenceTests(unittest.TestCase):
    def test_registry_url_is_primary_story_space_identity(self):
        metadata = (
            METADATA_START + "\nLOKÁCIA: [IZBA](https://trello.com/c/space)\n"
            "POSTAVY: BETY" + METADATA_END
        )
        desc = (
            metadata + "\n\nTitle\n\n### REKVIZITY V KONTEXTE\na\n\n"
            "### KONTINUITA\nb\n\n### ODKAZY\nc\n\n"
            "### RUČNÉ DOPLNENIA\nd\n\n### AKCIA A DIALÓGY\ne"
        )
        self.assertEqual(
            story_space_key(parse_description(desc), {"scene_id": "01/01"}),
            ("registry", ("https://trello.com/c/space",)),
        )

    def test_unlinked_ambiguous_space_uses_exact_source_only(self):
        metadata = (
            METADATA_START + "\nLOKÁCIA: HUDOBNÁ TRIEDA\nPOSTAVY: KIKO"
            + METADATA_END
        )
        desc = (
            metadata + "\n\nTitle\n\n### REKVIZITY V KONTEXTE\na\n\n"
            "### KONTINUITA\nb\n\n### ODKAZY\nc\n\n"
            "### RUČNÉ DOPLNENIA\nd\n\n### AKCIA A DIALÓGY\ne"
        )
        self.assertEqual(
            story_space_key(
                parse_description(desc),
                {"scene_id": "06/10", "location": "HUDOBNÁ TRIEDA"},
            ),
            ("source-exact", "hudobná trieda"),
        )

    def test_multi_space_scene_matches_a_shared_registry_space(self):
        self.assertTrue(same_story_space(
            ("registry", ("https://trello.com/c/a", "https://trello.com/c/b")),
            ("registry", ("https://trello.com/c/b",)),
        ))


if __name__ == "__main__":
    unittest.main()
