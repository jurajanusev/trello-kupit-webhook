import os
import unittest
from unittest.mock import patch

os.environ.setdefault("TRELLO_KEY", "test-key")
os.environ.setdefault("TRELLO_TOKEN", "test-token")

import app


BOARD = {
    "id": "board-id",
    "name": "RIVERDALE",
    "url": "https://trello.com/b/CzuD55PR",
    "closed": False,
    "shortLink": "CzuD55PR",
}
LISTS = [
    {"id": "scenes", "name": "SCENÁRE", "closed": True, "pos": 1},
    {
        "id": app.CIERNY_KAMEN_PROP_REGISTRY_LIST_ID,
        "name": "REGISTER REKVIZÍT",
        "closed": False,
        "pos": 2,
    },
    {
        "id": "test-list",
        "name": app.CIERNY_KAMEN_TEST_LIST_NAME,
        "closed": False,
        "pos": 3,
    },
]


def card(card_id, name, list_id, closed=True):
    return {
        "id": card_id,
        "name": name,
        "idList": list_id,
        "shortUrl": f"https://trello.com/c/{card_id}",
        "closed": closed,
    }


class CleanupEndpointTest(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()
        self.headers = {"X-Cleanup-Key": app.CIERNY_KAMEN_CLEANUP_KEY}

    def snapshot(self, cards, lists=None):
        responses = [BOARD, lists or LISTS, cards]
        return patch.object(app, "trello_get", side_effect=responses)

    def test_dry_run_is_read_only(self):
        cards = [
            card("scene-1", "01/01. INT. DOM", "scenes"),
            card("test-1", "[TEST] 02/28. INT. ŠKOLA", "test-list", False),
            card(
                "prop-1",
                "Alexova gitara",
                app.CIERNY_KAMEN_PROP_REGISTRY_LIST_ID,
            ),
        ]
        with self.snapshot(cards), patch.object(app, "trello_delete") as delete:
            response = self.client.post(
                "/api/cleanup-cierny-kamen-old-data?mode=dry-run",
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["writes"], 0)
        self.assertEqual(response.json["before"]["scene_cards_remaining"], 2)
        self.assertEqual(
            response.json["before"]["prop_registry_cards_remaining"], 1
        )
        delete.assert_not_called()

    def test_active_production_card_blocks_cleanup(self):
        cards = [card("scene-1", "01/01. INT. DOM", "test-list", False)]
        with self.snapshot(cards):
            response = self.client.post(
                "/api/cleanup-cierny-kamen-old-data?mode=apply&scope=scenes",
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json["status"], "blocked")

    def test_scene_batch_is_limited_and_read_back(self):
        before_cards = [
            card("scene-1", "01/01. INT. DOM", "scenes"),
            card("scene-2", "01/02. EXT. DOM", "scenes"),
        ]
        after_cards = [before_cards[1]]
        responses = [
            BOARD, LISTS, before_cards,
            BOARD, LISTS, after_cards,
        ]
        with patch.object(app, "trello_get", side_effect=responses), patch.object(
            app, "trello_delete"
        ) as delete:
            response = self.client.post(
                "/api/cleanup-cierny-kamen-old-data"
                "?mode=apply&scope=scenes&limit=1",
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["deleted_count"], 1)
        self.assertEqual(
            response.json["after"]["scene_cards_remaining"], 1
        )
        delete.assert_called_once_with("/cards/scene-1")

    def test_finalize_archives_only_empty_open_test_list(self):
        empty_cards = []
        closed_test_lists = [
            {**item, "closed": True} if item["id"] == "test-list" else item
            for item in LISTS
        ]
        responses = [
            BOARD, LISTS, empty_cards,
            BOARD, closed_test_lists, empty_cards,
        ]
        with patch.object(app, "trello_get", side_effect=responses), patch.object(
            app, "trello_put_body"
        ) as put:
            response = self.client.post(
                "/api/cleanup-cierny-kamen-old-data"
                "?mode=apply&scope=finalize",
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json["archived_lists"]), 1)
        put.assert_called_once_with(
            "/lists/test-list", {"closed": "true"}
        )

    def test_repeated_clean_apply_is_idempotent(self):
        responses = [BOARD, LISTS, [], BOARD, LISTS, []]
        with patch.object(app, "trello_get", side_effect=responses), patch.object(
            app, "trello_delete"
        ) as delete:
            response = self.client.post(
                "/api/cleanup-cierny-kamen-old-data"
                "?mode=apply&scope=scenes",
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["deleted_count"], 0)
        delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
