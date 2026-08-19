import sys
import types
import unittest

if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.jsonify = lambda value: value
    flask_stub.request = None
    sys.modules["flask"] = flask_stub

from cierny_kamen_reference_identity_0109 import identity_core, split_sections


class ReferenceIdentityTest(unittest.TestCase):
    def test_alias_normalization_is_accent_and_case_insensitive(self):
        from meeting_notes_dryrun import folded
        self.assertEqual(folded("Čln Jakuba a Sáry"), folded("CLN JAKUBA A SARY"))

    def test_identity_core_strips_only_technical_wrappers(self):
        value = "<n> **Drevená pramica Jakuba a Sáry** — *na vode | TU: prevrátená* | KARTA: https://trello.com/c/x"
        self.assertEqual("Drevená pramica Jakuba a Sáry", identity_core(value))

    def test_identity_core_preserves_name_hyphen(self):
        self.assertEqual("Fotoaparát - analógový", identity_core("**Fotoaparát - analógový** | KARTA: https://trello.com/c/x"))

    def test_sections_are_ordered(self):
        rows = split_sections("## Názov\nText\n\n### NAVIGÁCIA\nLinks\n\n## METADATA\nM")
        self.assertEqual(["Názov", "NAVIGÁCIA", "METADATA"], [row["title"] for row in rows])


if __name__ == "__main__":
    unittest.main()
