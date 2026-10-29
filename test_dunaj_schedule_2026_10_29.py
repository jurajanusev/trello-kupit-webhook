import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault("TRELLO_KEY", "test-key")
os.environ.setdefault("TRELLO_TOKEN", "test-token")
import app


class October29Tests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads((Path(__file__).parent / app.DUNAJ_CURRENT_SCHEDULE_FILE).read_text(encoding="utf-8"))
        self.rows = app.canonicalize_dunaj_schedule_rows(self.document["rows"])
        self.dates = sorted({r["shooting_date"] for r in self.rows})[:7]
        self.lists = [
            {"id": "old", "name": "SERIA 15,16", "pos": 100},
            {"id": "series", "name": "SERIA 17,18", "pos": 1000},
            {"id": "other", "name": "REKVIZITY", "pos": 2000},
            {"id": "shot", "name": "17/18 NATOČENÉ OBRAZY", "pos": 3000},
        ]
        for i, date in enumerate(reversed(self.dates)):
            year, month, day = map(int, date.split("-"))
            self.lists.append({"id": date, "name": f"{day}.{month}.", "pos": 10000 + i * 1000})
        self.cards = [{"id": r["scene_id"], "name": r["scene_id"] + ". INT. TEST", "desc": "Ručné poznámky", "idList": "series", "shortUrl": "https://trello.com/c/" + str(i), "pos": i + 1, "due": None, "dueComplete": False} for i, r in enumerate(self.rows)]
        self.writes = []

    def get(self, path, params=None):
        if path == "/boards/qCPeWA3e":
            return {"id": "board", "name": "Dunaj", "url": "https://trello.com/b/qCPeWA3e"}
        if path == "/boards/board/lists":
            return copy.deepcopy(self.lists)
        if path.startswith("/lists/") and path.endswith("/cards"):
            list_id = path.split("/")[2]
            return copy.deepcopy([c for c in self.cards if c["idList"] == list_id])
        raise AssertionError((path, params))

    def put(self, path, payload):
        self.writes.append((path, payload))
        items = self.lists if path.startswith("/lists/") else self.cards
        item = next(c for c in items if path == ("/lists/" if items is self.lists else "/cards/") + c["id"])
        item.update(payload)
        return copy.deepcopy(item)

    def call(self, query):
        with patch.object(app, "trello_get", side_effect=self.get), patch.object(app, "trello_put_body", side_effect=self.put):
            return app.app.test_client().post("/api/sync-dunaj-schedule?" + query, headers={"X-Sync-Key": app.DUNAJ_CURRENT_SCHEDULE_KEY})

    def test_complete_source_and_seven_shooting_days(self):
        self.assertEqual(len(self.rows), 333)
        self.assertEqual(len({r["scene_id"] for r in self.rows}), 333)
        self.assertEqual(self.document["source"], app.DUNAJ_CURRENT_SOURCE_LABEL)
        self.assertIn("02/30", {r["scene_id"] for r in self.rows})
        self.assertEqual(self.dates, ["2026-10-30", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-08"])
        result = self.call("mode=dry-run").get_json()
        self.assertEqual(result["missing_count"], 0)
        self.assertEqual(result["window_duplicates_count"], 0)
        self.assertGreater(result["list_order_pending_count"], 0)
        self.assertFalse(self.writes)

    def test_apply_places_chronological_dates_immediately_after_current_series(self):
        count = sum(r["shooting_date"] in self.dates for r in self.rows)
        response = self.call(f"mode=apply-window&start={count - 1}&limit=1")
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["list_order_errors_count"], 0)
        ordered = [l["id"] for l in sorted(self.lists, key=lambda l: l["pos"])]
        i = ordered.index("series")
        self.assertEqual(ordered[i+1:i+8], self.dates)
        self.assertEqual(self.call("mode=dry-run").get_json()["list_order_pending_count"], 0)
        self.assertTrue(all("Ručné poznámky" in c["desc"] for c in self.cards))

    def test_missing_current_series_blocks_writes(self):
        self.lists = [l for l in self.lists if l["id"] != "series"]
        response = self.call("mode=apply-window")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(self.writes)


if __name__ == "__main__":
    unittest.main()
