import sys
import types
import unittest


if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.jsonify = lambda value: value
    flask_stub.request = None
    sys.modules["flask"] = flask_stub

from cierny_kamen_reference_0116 import (
    METADATA_END,
    METADATA_START,
    desired_description,
    desired_set_item,
    metadata_characters,
    metadata_location_urls,
    parse_description,
)


DESC = f"""{METADATA_START}
POSTAVY: BETY, KIKO
LOKÁCIA: [DOM BETY – IZBA BETY](https://trello.com/c/space)
{METADATA_END}

#### **Kiko a Bety sa bavia o Alexovi**

### REKVIZITY V KONTEXTE
props

### KONTINUITA
continuity

### ODKAZY
links

### RUČNÉ DOPLNENIA
manual

### AKCIA A DIALÓGY
verbatim"""


class ReferenceCardTests(unittest.TestCase):
    def test_metadata_and_required_sections_are_unique(self):
        parsed = parse_description(DESC)
        self.assertEqual(metadata_characters(parsed["metadata"]), ["BETY", "KIKO"])
        self.assertEqual(metadata_location_urls(parsed["metadata"]), [
            "https://trello.com/c/space"
        ])

    def test_reorder_preserves_section_text_and_moves_metadata(self):
        related = "### NADVÄZNÉ OBRAZY\n\n### Rovnaký priestor\n- Predchádzajúci: —"
        result = desired_description(DESC, related)
        self.assertTrue(result.endswith(parse_description(DESC)["metadata"]))
        self.assertIn("### RUČNÉ DOPLNENIA\nmanual", result)
        self.assertLess(result.index(related), result.index("### RUČNÉ DOPLNENIA"))

    def test_set_item_only_appends_missing_real_url(self):
        original = "Set — prostredie obrazu 01/16: DOM BETY – IZBA BETY"
        url = "https://trello.com/c/space"
        desired = desired_set_item(original, [url])
        self.assertEqual(desired, original + " | KARTA: " + url)
        self.assertEqual(desired_set_item(desired, [url]), desired)

    def test_ambiguous_sections_block(self):
        with self.assertRaises(ValueError):
            parse_description(DESC + "\n\n### ODKAZY\nduplicate")


if __name__ == "__main__":
    unittest.main()

