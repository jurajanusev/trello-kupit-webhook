import unittest
import sys
import types


if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.jsonify = lambda value: value
    flask_stub.request = None
    sys.modules["flask"] = flask_stub

from board_routing import resolve_target_list_id
from dok4_board_guard_repair import (
    SYNC_END,
    SYNC_START,
    exact_auto_only,
    replace_marker_preserving_manual,
)


DOK4_BOARD_ID = "board-dok4"
RIVERDALE_BOARD_ID = "board-riverdale"
DOK4_SOURCE = "source-dok4"
DOK4_TODO = "todo-dok4"
RIVERDALE_TODO = "todo-riverdale"


class BoardOwnershipRoutingTests(unittest.TestCase):
    def resolve(self, configured_target):
        owners = {
            DOK4_TODO: DOK4_BOARD_ID,
            RIVERDALE_TODO: RIVERDALE_BOARD_ID,
        }
        return resolve_target_list_id(
            {"idBoard": DOK4_BOARD_ID, "idList": DOK4_SOURCE},
            {DOK4_SOURCE: {"target_list_id": configured_target}},
            {"lzNy4AtY": DOK4_TODO, "CzuD55PR": RIVERDALE_TODO},
            lambda board_id: "lzNy4AtY" if board_id == DOK4_BOARD_ID else None,
            owners.get,
        )

    def test_dok4_routes_to_dok4(self):
        self.assertEqual(self.resolve(DOK4_TODO), DOK4_TODO)

    def test_dok4_never_routes_to_riverdale(self):
        self.assertEqual(self.resolve(RIVERDALE_TODO), DOK4_TODO)

    def test_unmapped_dok4_date_list_uses_dok4_fallback(self):
        owners = {DOK4_TODO: DOK4_BOARD_ID}
        result = resolve_target_list_id(
            {"idBoard": DOK4_BOARD_ID, "idList": "unmapped-date-list"},
            {},
            {"lzNy4AtY": DOK4_TODO},
            lambda _board_id: "lzNy4AtY",
            owners.get,
        )
        self.assertEqual(result, DOK4_TODO)

    def test_unsupported_board_is_ignored(self):
        result = resolve_target_list_id(
            {"idBoard": "unknown", "idList": "source"},
            {"source": {"target_list_id": RIVERDALE_TODO}},
            {"lzNy4AtY": DOK4_TODO},
            lambda _board_id: "not-supported",
            lambda _list_id: RIVERDALE_BOARD_ID,
        )
        self.assertIsNone(result)


class RepairSafetyTests(unittest.TestCase):
    def test_marker_replacement_preserves_manual_text(self):
        old_marker = f"{SYNC_START}\nold\n{SYNC_END}"
        new_marker = f"{SYNC_START}\nnew\n{SYNC_END}"
        original = old_marker + "\n\nRUČNÁ POZNÁMKA"
        self.assertEqual(
            replace_marker_preserving_manual(original, new_marker),
            new_marker + "\n\nRUČNÁ POZNÁMKA",
        )

    def test_wrong_card_is_archivable_only_when_fully_automatic(self):
        marker = f"{SYNC_START}\nauto\n{SYNC_END}"
        card = {
            "desc": marker,
            "badges": {"attachments": 0, "checkItems": 0, "comments": 0},
        }
        self.assertTrue(exact_auto_only(card))
        card["desc"] += "\nmanual"
        self.assertFalse(exact_auto_only(card))

    def test_invalid_default_is_not_used(self):
        result = resolve_target_list_id(
            {"idBoard": DOK4_BOARD_ID, "idList": DOK4_SOURCE},
            {},
            {"lzNy4AtY": DOK4_TODO},
            lambda _board_id: "lzNy4AtY",
            lambda _list_id: RIVERDALE_BOARD_ID,
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
