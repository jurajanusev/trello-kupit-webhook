import copy
import unittest
from unittest.mock import patch

from test_dunaj_schedule_2026_10_29 import October29Tests
import app


class November08Tests(October29Tests):
    def test_production_one_off_route_is_disabled(self):
        with patch.object(app, "trello_get", side_effect=AssertionError("unauthorized request")):
            response = app.app.test_client().post("/api/sync-dunaj-schedule")
        self.assertIn(response.status_code, (403, 410))

    def test_complete_source_and_seven_shooting_days(self):
        self.assertEqual(len(self.rows), 411)
        self.assertEqual(len({r['scene_id'] for r in self.rows}), 411)
        self.assertEqual(self.dates, ['2026-11-09', '2026-11-10', '2026-11-11', '2026-11-12', '2026-11-16', '2026-11-17', '2026-11-18'])
        special = [r for r in self.rows if r['episode'] == 'V']
        self.assertEqual([r['scene_id'] for r in special], ['V/5', 'V/8'])
        self.assertTrue(all(r['shooting_date'] == '2026-11-17' for r in special))
        self.assertEqual(self.rows[-1]['shooting_date'], '2026-12-20')
        self.assertIsNone(self.rows[-1]['shooting_day'])
        result = self.call('mode=dry-run').get_json()
        self.assertEqual(result['window_schedule_rows'], 97)
        self.assertEqual(result['window_missing_count'], 0)
        self.assertEqual(result['duplicate_scene_ids_count'], 0)
        self.assertFalse(self.writes)

    def test_missing_placeholder_is_marked_and_not_created_twice(self):
        missing = next(c for c in self.cards if c['id'] == 'V/5')
        self.cards.remove(missing)
        def post(path, payload):
            self.assertEqual(path, '/cards')
            card = dict(payload, id='placeholder', shortUrl='https://trello.com/c/test', dueComplete=False)
            self.cards.append(card)
            return copy.deepcopy(card)
        with patch.object(app, 'trello_post_body', side_effect=post):
            result = self.call('mode=create-window-missing').get_json()
        self.assertEqual(result['created_count'], 1)
        self.assertIn('[DOPLNIT]', self.cards[-1]['name'])
        self.assertIn('DOČASNÁ KARTA', self.cards[-1]['desc'])
        self.assertEqual(self.call('mode=dry-run').get_json()['window_missing_count'], 0)


if __name__ == '__main__':
    unittest.main()
