import sys
import types
import unittest


if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.jsonify = lambda value: value
    flask_stub.request = None
    sys.modules["flask"] = flask_stub

from cierny_kamen_prop_markdown_format import (
    classify_item,
    format_registry_item,
    remove_allowed_delimiters,
)


URL = "https://trello.com/c/AbCd1234"


class PropMarkdownFormatTests(unittest.TestCase):
    def test_formats_expected_example(self):
        before = (
            "<n> Betin osobn\u00fd mobil \u2014 \u010d\u00edta spr\u00e1vu | "
            "TU: zapnut\u00fd displej | \u2192 01/19 | KARTA: " + URL
        )
        after = format_registry_item(before, "Betin osobn\u00fd mobil", URL)
        self.assertEqual(
            after,
            "<n> **Betin osobn\u00fd mobil** \u2014 *\u010d\u00edta spr\u00e1vu | "
            "TU: zapnut\u00fd displej | \u2192 01/19* | KARTA: " + URL,
        )
        self.assertEqual(
            remove_allowed_delimiters(after), remove_allowed_delimiters(before)
        )

    def test_name_with_dash_is_not_split(self):
        name = "S\u00e1rina \u0161atka \u2014 01/11FLASH"
        before = name + " \u2014 le\u017e\u00ed na stole | KARTA: " + URL
        self.assertEqual(
            format_registry_item(before, name, URL),
            f"**{name}** \u2014 *le\u017e\u00ed na stole* | KARTA: {URL}",
        )

    def test_without_context(self):
        self.assertEqual(
            format_registry_item("Alicin mobil | KARTA: " + URL, "Alicin mobil", URL),
            "**Alicin mobil** | KARTA: " + URL,
        )

    def test_does_not_add_n_marker(self):
        result = format_registry_item(
            "Alicin mobil \u2014 zvon\u00ed | KARTA: " + URL,
            "Alicin mobil", URL,
        )
        self.assertFalse(result.startswith("<n>"))

    def test_idempotent(self):
        before = "Mobil \u2014 zvon\u00ed | KARTA: " + URL
        once = format_registry_item(before, "Mobil", URL)
        self.assertEqual(format_registry_item(once, "Mobil", URL), once)

    def test_preserves_suffix_spacing_verbatim(self):
        before = "Mobil \u2014 zvon\u00ed  |  KARTA:  " + URL
        after = format_registry_item(before, "Mobil", URL)
        self.assertTrue(after.endswith("  |  KARTA:  " + URL))

    def test_verified_identity_allows_verbatim_comma_context(self):
        before = "papiere s notami, ktor\u00e9 uklad\u00e1 Olasov\u00e1 | KARTA: " + URL
        self.assertEqual(
            format_registry_item(before, "papiere s notami", URL),
            "**papiere s notami***, ktor\u00e9 uklad\u00e1 Olasov\u00e1* | KARTA: " + URL,
        )

    def test_rejects_alias_instead_of_canonical_name(self):
        with self.assertRaisesRegex(ValueError, "canonical"):
            format_registry_item(
                "Betin mobil \u2014 zvon\u00ed | KARTA: " + URL,
                "Betin osobn\u00fd mobil", URL,
            )

    def test_companion_is_skipped(self):
        result = classify_item(
            "\u21b3 automatick\u00fd kontext | KARTA: " + URL, {}
        )
        self.assertEqual(result["action"], "skip_companion")


if __name__ == "__main__":
    unittest.main()
