import sys
import types
import unittest


if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.jsonify = lambda value: value
    flask_stub.request = None
    sys.modules["flask"] = flask_stub

from cierny_kamen_reference_all import (
    build_reference_description,
    mobile_master_description,
    parse_reference_layout,
    same_story_space,
    story_space_key,
)
from cierny_kamen_reference_0116 import (
    METADATA_END, METADATA_START,
)


class AllReferenceTests(unittest.TestCase):
    def test_mobile_master_description_is_deterministic_and_linked(self):
        result = mobile_master_description([
            {"scene_id": "03/07", "card_url": "https://trello.com/c/b"},
            {"scene_id": "01/16", "card_url": "https://trello.com/c/a"},
        ])
        self.assertIn("KANONICKÝ NÁZOV: Betin osobný mobil", result)
        self.assertLess(result.index("[01/16]"), result.index("[03/07]"))
        self.assertEqual(result.count("https://trello.com/c/"), 2)

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
            story_space_key(
                parse_reference_layout(desc, "Title"), {"scene_id": "01/01"}
            ),
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
                parse_reference_layout(desc, "Title"),
                {"scene_id": "06/10", "location": "HUDOBNÁ TRIEDA"},
            ),
            ("source-exact", "hudobná trieda"),
        )

    def test_multi_space_scene_matches_a_shared_registry_space(self):
        self.assertTrue(same_story_space(
            ("registry", ("https://trello.com/c/a", "https://trello.com/c/b")),
            ("registry", ("https://trello.com/c/b",)),
        ))

    def test_legacy_continuity_becomes_reference_nadvaznost(self):
        metadata = (
            METADATA_START + "\nLOKÁCIA: [IZBA](https://trello.com/c/space)\n"
            "POSTAVY: BETY" + METADATA_END
        )
        desc = (
            metadata + "\n\n#### **Title**\n\n### REKVIZITY V KONTEXTE\na\n\n"
            "### KONTINUITA\nmanual continuity\n\n### ODKAZY\nc\n\n"
            "### RUČNÉ DOPLNENIA\nd\n\n### AKCIA A DIALÓGY\ne"
        )
        parsed = parse_reference_layout(desc, "Title")
        result = build_reference_description(
            parsed, "Title", "### KONTINUITA PRIESTORU\n\n- Predchádzajúci: —",
            "### KONTINUITA POSTÁV\n\n- BETY: ← — | → —",
        )
        self.assertTrue(result.startswith("## Title"))
        self.assertIn("### NADVAZNOSŤ\n\nmanual continuity", result)
        self.assertTrue(result.endswith(metadata))


if __name__ == "__main__":
    unittest.main()
