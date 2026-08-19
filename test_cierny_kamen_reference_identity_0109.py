import sys
import types
import unittest

if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.jsonify = lambda value: value
    flask_stub.request = None
    sys.modules["flask"] = flask_stub

from cierny_kamen_reference_identity_0109 import (
    _duplicate_detail_for_apply,
    _pair_plan, desired_0109_description, identity_core, split_sections,
)
from cierny_kamen_prop_identity_resolution import resolve_identity


class ReferenceIdentityTest(unittest.TestCase):
    def test_archived_duplicate_uses_dry_run_snapshot(self):
        calls = []
        row = {
            "id": "archived-id", "name": "Old master", "url": "https://trello.com/c/old",
            "closed": True, "list": "REGISTER REKVIZÍT", "attachments": [],
        }
        detail = _duplicate_detail_for_apply({"trello_get": lambda *args: calls.append(args)}, row)
        self.assertEqual([], calls)
        self.assertEqual("https://trello.com/c/old", detail["shortUrl"])
        self.assertTrue(detail["closed"])

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

    def test_resolved_pair_is_idempotent(self):
        rows = [{"text": "desired", "state": "incomplete", "urls": ["https://trello.com/c/x"],
                 "companion": False}]
        plan = _pair_plan(rows, "https://trello.com/c/x", "desired")
        self.assertTrue(plan["resolved"])
        self.assertFalse(plan["pending"])
        self.assertIsNone(plan["conflict"])

    def test_description_moves_metadata_to_end_and_deduplicates_characters(self):
        desc = (
            "## Názov\n\n## KONTINUITA PRIESTORU\n- Predchádzajúci: —\n"
            "## KONTINUITA POSTÁV\n- A: x\n- A: x\n- B: y\n"
            "## RUČNÉ DOPLNENIA\nručne\n## AKCIA A DIALÓGY\nakcia\n"
            "<!-- CIERNY-KAMEN-SCHEDULE-METADATA:START -->m"
            "<!-- CIERNY-KAMEN-SCHEDULE-METADATA:END -->"
        )
        desired, conflict = desired_0109_description(desc)
        self.assertIsNone(conflict)
        self.assertEqual(1, desired.count("- A: x"))
        self.assertTrue(desired.endswith("<!-- CIERNY-KAMEN-SCHEDULE-METADATA:END -->"))
        desired_again, conflict_again = desired_0109_description(desired)
        self.assertIsNone(conflict_again)
        self.assertEqual(desired, desired_again)

    def test_master_url_precedes_alias(self):
        result = resolve_identity(
            "Alias | KARTA: https://trello.com/c/x",
            url_to_canonical={"https://trello.com/c/x": "URL identity"},
            canonical_names=("Alias identity",), aliases={"Alias identity": ("Alias",)},
        )
        self.assertEqual("URL identity", result["canonical"])
        self.assertEqual("master_url", result["evidence"])


if __name__ == "__main__":
    unittest.main()
