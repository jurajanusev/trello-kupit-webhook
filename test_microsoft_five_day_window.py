import os
import unittest
from datetime import datetime
from unittest.mock import patch

os.environ.setdefault("TRELLO_KEY", "test-key")
os.environ.setdefault("TRELLO_TOKEN", "test-token")
import app


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 10, 8, tzinfo=tz)


class FiveDayWindowTests(unittest.TestCase):
    def run_sync(self, cards, tasks=(), query="days=5", mode="dry-run"):
        def trello(path, params):
            return [{"id": "todo", "name": "ToDo"}] if path.endswith("/lists") else cards

        with patch.multiple(app, microsoft_enabled=lambda: True,
                            get_microsoft_access_token=lambda: "test",
                            trello_get=trello, graph_get_all=lambda *args: list(tasks),
                            datetime=FixedDateTime), patch.object(app, "graph_post") as post, \
                patch.object(app, "graph_patch") as update:
            response = app.app.test_client().post(
                f"/api/sync-dunaj-microsoft-todo?mode={mode}&{query}",
                headers={"X-Microsoft-Sync-Key": "dunaj-ms-todo-sync-19jul-84c2f1a7"})
            return response.status_code, response.get_json(), post.call_count, update.call_count

    def card(self, name, due, **extra):
        return {"id": name, "name": name, "shortUrl": f"https://trello.com/c/{name}",
                "due": due, **extra}

    def test_local_midnight_and_fifth_day_boundaries(self):
        cards = [self.card("today", "2026-11-09T23:30:00Z"),
                 self.card("last", "2026-11-14T22:30:00Z"),
                 self.card("late", "2026-11-14T23:30:00Z"),
                 self.card("past", "2026-11-09T12:00:00Z")]
        status, data, posts, patches = self.run_sync(cards)
        self.assertEqual(status, 200)
        self.assertEqual({x["title"] for x in data["sample"]}, {"today", "last"})
        self.assertEqual(data["window_end"], "2026-11-14")
        self.assertEqual(next(x["trello_due"] for x in data["sample"] if x["title"] == "today"), "2026-11-10")
        self.assertEqual((posts, patches), (0, 0))

    def test_excludes_completed_undated_invalid_and_archived_cards(self):
        cards = [self.card("complete", "2026-11-10T12:00:00Z", dueComplete=True),
                 self.card("undated", None), self.card("invalid", "invalid"),
                 self.card("archived", "2026-11-10T12:00:00Z", closed=True)]
        self.assertEqual(self.run_sync(cards)[1]["trello_cards"], 0)

    def test_completed_microsoft_task_is_preserved(self):
        card = self.card("done", "2026-11-10T12:00:00Z")
        task = {"id": "done-task", "title": "done", "status": "completed",
                "body": {"content": card["shortUrl"]}}
        _, data, posts, patches = self.run_sync([card], [task], mode="apply")
        self.assertEqual(data["completed_preserved"], 1)
        self.assertEqual((posts, patches), (0, 0))

    def test_title_collision_in_another_project_does_not_update_it(self):
        card = self.card("camera", "2026-11-10T12:00:00Z")
        task = {"id": "other", "title": "camera", "body": {"content": "SYNC PROJECT: DOK4\n"}}
        self.assertEqual(self.run_sync([card], [task])[1]["to_create"], 1)

    def test_bad_windows_are_rejected(self):
        for value in ("0", "32", "-1", "x", "1.5", ""):
            self.assertEqual(self.run_sync([], query=f"days={value}")[0], 400)

    def test_full_sync_without_window_still_includes_undated_cards(self):
        _, data, _, _ = self.run_sync([self.card("undated", None)], query="")
        self.assertEqual(data["to_create"], 1)
        self.assertNotIn("window_start", data)


if __name__ == "__main__":
    unittest.main()
