import re
import sys
import types
import unittest


if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.jsonify = lambda value: value
    flask_stub.request = None
    sys.modules["flask"] = flask_stub

from meeting_notes_dryrun import (
    audit_project, classify_item, list_kind, normalized_text,
)


class MeetingNotesDryRunTest(unittest.TestCase):
    def test_list_classification_excludes_shot_and_support_lists(self):
        self.assertEqual("shot", list_kind("NATOČENÉ 15/16"))
        self.assertEqual("todo", list_kind("ToDo"))
        self.assertEqual("registry", list_kind("REGISTER REKVIZÍT"))
        self.assertEqual("registry", list_kind("BETY – OS. REKVIZITY"))
        self.assertEqual("active", list_kind("VŠETKY EPIZÓDY"))
        self.assertEqual("active", list_kind("18.8."))

    def test_classifier_never_guesses_questions(self):
        result = classify_item("REKVIZITY", "Overiť, či je to Alicin mobil?")
        self.assertEqual("ambiguous", result["classification"])
        self.assertEqual("high", result["confidence"])

    def test_classifier_uses_explicit_operation_and_context(self):
        self.assertEqual(
            "cancelled",
            classify_item("POZNÁMKY Z PORADY", "Zrušiť starú tašku")["classification"],
        )
        self.assertEqual(
            "changed",
            classify_item("INFO Z PORADY", "Zmeniť farbu na čiernu")["classification"],
        )
        self.assertEqual(
            "added",
            classify_item("REKVIZITY", "Alicin mobil")["classification"],
        )

    def test_normalization_removes_only_technical_formatting(self):
        value = normalized_text(
            "<n> **Betin mobil** — *zapnutý* | KARTA: https://trello.com/c/abc"
        )
        self.assertIn("betin mobil", value)
        self.assertIn("zapnuty", value)
        self.assertNotIn("trello", value)

    def test_full_project_audit_is_read_only_and_evidence_based(self):
        lists = [
            {"id": "active", "name": "VŠETKY EPIZÓDY", "closed": False},
            {"id": "shot", "name": "NATOČENÉ", "closed": False},
            {"id": "todo", "name": "ToDo", "closed": False},
            {"id": "registry", "name": "REGISTER REKVIZÍT", "closed": False},
            {"id": "archived", "name": "Starý", "closed": True},
        ]
        cards = {
            "active": [{
                "id": "scene", "name": "01/01. INT. DOM", "desc": "",
                "shortUrl": "https://trello.com/c/scene", "idList": "active",
                "checklists": [
                    {
                        "id": "meeting", "name": "POZNÁMKY Z PORADY", "pos": 1,
                        "checkItems": [
                            {"id": "done", "name": "[z] Pripraviť lampu", "state": "incomplete", "pos": 1},
                            {"id": "change", "name": "Zmeniť farbu tašky na čiernu", "state": "incomplete", "pos": 2},
                            {"id": "question", "name": "Overiť auto?", "state": "complete", "pos": 3},
                        ],
                    },
                    {
                        "id": "props", "name": "REKVIZITY", "pos": 2,
                        "checkItems": [{
                            "id": "linked", "name": "Alicin mobil | KARTA: https://trello.com/c/master",
                            "state": "incomplete", "pos": 1,
                        }],
                    },
                ],
            }],
            "shot": [{
                "id": "shot-scene", "name": "01/02. EXT. DOM", "desc": "",
                "shortUrl": "https://trello.com/c/shot", "idList": "shot",
                "checklists": [],
            }],
            "todo": [{
                "id": "todo-card", "name": "Pripraviť lampu", "desc": "[z] Pripraviť lampu",
                "shortUrl": "https://trello.com/c/todo", "idList": "todo",
            }],
            "registry": [{
                "id": "master", "name": "Alicin mobil", "desc": "Alicin mobil",
                "shortUrl": "https://trello.com/c/master", "idList": "registry",
            }],
        }
        calls = []

        def trello_get(path, params):
            calls.append(path)
            if path == "/boards/ref":
                return {"id": "board", "name": "Board", "url": "https://trello.com/b/ref"}
            if path == "/boards/board/lists":
                return lists
            match = re.match(r"/lists/([^/]+)/cards", path)
            if match:
                return cards.get(match.group(1), [])
            raise AssertionError(path)

        result = audit_project({
            "trello_get": trello_get,
            "scene_id_from_card_name": lambda name: name.split(".", 1)[0] if "/" in name else None,
        }, {"board_ref": "ref", "name": "Test"})

        self.assertEqual(1, result["counts"]["scene_cards_scanned"])
        self.assertEqual(4, result["counts"]["checklist_items"])
        self.assertEqual(2, result["counts"]["already_processed"])
        self.assertEqual(2, result["counts"]["review_items"])
        self.assertEqual({"ambiguous": 1, "changed": 1}, result["classification_counts"])
        self.assertNotIn("/lists/shot/cards", calls)
        self.assertEqual(1, len(result["finding_cards"]))
        returned = [
            item for checklist in result["finding_cards"][0]["checklists"]
            for item in checklist["items"]
        ]
        self.assertEqual({"change", "question"}, {item["id"] for item in returned})


if __name__ == "__main__":
    unittest.main()
