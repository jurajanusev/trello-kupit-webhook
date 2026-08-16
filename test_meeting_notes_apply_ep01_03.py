import sys
import types
import unittest

if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.jsonify = lambda value: value
    flask_stub.request = None
    sys.modules["flask"] = flask_stub

from meeting_notes_apply_ep01_03 import (
    END, ITEM_MARKER, START, enrich_description, protected_snapshot,
    scene_episode, source_notes,
)


class MeetingNotesApplyTest(unittest.TestCase):
    def test_scene_episode(self):
        self.assertEqual(1, scene_episode("01/2LP"))
        self.assertEqual(3, scene_episode("3/47LP"))
        self.assertIsNone(scene_episode("card"))

    def test_resolved_and_ambiguous_notes_are_separated(self):
        card = {"desc": "", "checklists": [{
            "id": "c", "name": "INFO Z PORADY", "pos": 1,
            "checkItems": [
                {"id": "ok", "name": "DREVENA PRAMICA", "state": "incomplete", "pos": 1},
                {"id": "ask", "name": "KABRIOLET - ??", "state": "incomplete", "pos": 2},
            ],
        }]}
        resolved, ambiguous, ignored = source_notes(card)
        self.assertEqual(["ok"], [row["item_id"] for row in resolved])
        self.assertEqual(["ask"], [row["item_id"] for row in ambiguous])
        self.assertEqual([], ignored)

    def test_description_change_is_bounded_and_idempotent(self):
        desc = (
            "## Názov\n\n## RUČNÉ DOPLNENIA\n\nRučný text.\n\n"
            "## AKCIA A DIALÓGY\n\nPôvodný scenár.\n"
        )
        note = {"item_id": "abc", "checklist": "INFO Z PORADY", "text": "DREVENA PRAMICA"}
        changed, pending, conflict = enrich_description(desc, [note])
        self.assertIsNone(conflict)
        self.assertEqual(1, len(pending))
        self.assertIn(START, changed)
        self.assertIn(END, changed)
        self.assertIn(f"{ITEM_MARKER}abc", changed)
        self.assertIn("Ručný text.", changed)
        self.assertIn("Pôvodný scenár.", changed)
        unchanged, pending_again, conflict_again = enrich_description(changed, [note])
        self.assertEqual(changed, unchanged)
        self.assertEqual([], pending_again)
        self.assertIsNone(conflict_again)

    def test_missing_manual_boundary_is_a_conflict(self):
        note = {"item_id": "abc", "checklist": "INFO Z PORADY", "text": "DREVENA PRAMICA"}
        changed, pending, conflict = enrich_description("## AKCIA A DIALÓGY\nText", [note])
        self.assertEqual("## AKCIA A DIALÓGY\nText", changed)
        self.assertEqual([], pending)
        self.assertTrue(conflict)

    def test_snapshot_detects_text_state_and_description_changes(self):
        card = {"desc": "a", "checklists": [{
            "id": "c", "name": "INFO Z PORADY", "pos": 1,
            "checkItems": [{"id": "i", "name": "x", "state": "incomplete", "pos": 1}],
        }]}
        original = protected_snapshot(card)
        card["checklists"][0]["checkItems"][0]["state"] = "complete"
        self.assertNotEqual(original, protected_snapshot(card))


if __name__ == "__main__":
    unittest.main()
