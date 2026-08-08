import sys
import types
import unittest


if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.jsonify = lambda value: value
    flask_stub.request = None
    sys.modules["flask"] = flask_stub

from cierny_kamen_personal_props_markdown import (
    explicit_main_characters,
    format_item,
    parse_item,
)


URL = "https://trello.com/c/AbCd1234"


class PersonalPropsMarkdownTests(unittest.TestCase):
    def test_formats_continuity_item_without_moving_marker_or_suffix(self):
        before = (
            "<n> Betin osobn\u00fd mobil \u2014 \u010d\u00edta spr\u00e1vu | "
            "TU: zapnut\u00fd displej | \u2192 01/19 | KARTA: " + URL
        )
        self.assertEqual(
            format_item(before),
            "<n> **Betin osobn\u00fd mobil** \u2014 *\u010d\u00edta spr\u00e1vu | "
            "TU: zapnut\u00fd displej | \u2192 01/19* | KARTA: " + URL,
        )

    def test_formats_item_without_context(self):
        self.assertEqual(
            format_item("Alicin mobil | KARTA: " + URL),
            "**Alicin mobil** | KARTA: " + URL,
        )

    def test_does_not_add_continuity_marker(self):
        formatted = format_item("Alicin mobil \u2014 zvon\u00ed | KARTA: " + URL)
        self.assertFalse(formatted.startswith("<n>"))

    def test_is_idempotent(self):
        before = (
            "<n> Betin osobn\u00fd mobil \u2014 \u010d\u00edta spr\u00e1vu | "
            "TU: zapnut\u00fd displej | KARTA: " + URL
        )
        once = format_item(before)
        self.assertEqual(format_item(once), once)

    def test_companion_is_unchanged(self):
        before = "\u21b3 automatick\u00fd kontext | KARTA: " + URL
        self.assertEqual(parse_item(before)["kind"], "companion")
        self.assertEqual(format_item(before), before)

    def test_rejects_ambiguous_delimiters(self):
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            format_item("Betin *mobil* | KARTA: " + URL)

    def test_main_characters_are_not_inferred(self):
        self.assertIsNone(explicit_main_characters({}, "bez defin\u00edcie"))

    def test_reads_explicit_main_characters_from_payload(self):
        self.assertEqual(
            explicit_main_characters(
                {"main_characters": ["BETY", "ALEX"]}, ""
            ),
            {
                "source": "payload.main_characters",
                "names": ["BETY", "ALEX"],
            },
        )


if __name__ == "__main__":
    unittest.main()
