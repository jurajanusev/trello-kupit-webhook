import copy
import json
from pathlib import Path
import unittest

from update_dok4_plan_local import build_state, summary, apply, create_missing_placeholders

ROOT = Path(__file__).parent


class TrelloFixture:
    def __init__(self):
        self.lists = [
            {'id':'anchor', 'name':'VŠETKY EPIZÓDY', 'pos':1000},
            {'id':'other', 'name':'REKVIZITY', 'pos':2000},
            {'id':'past', 'name':'7.11.', 'pos':1100},
            {'id':'stale', 'name':'30.12.', 'pos':4000},
        ]
        self.cards = [
            {'id':'past', 'name':'99/1. TEST', 'idList':'past', 'shortUrl':'https://trello.com/c/past', 'due':'2026-11-07T10:00:00.000Z', 'dueComplete':True, 'pos':1},
            {'id':'stale', 'name':'99/2. TEST', 'idList':'stale', 'shortUrl':'https://trello.com/c/stale', 'due':'2026-12-30T10:00:00.000Z', 'dueComplete':True, 'pos':1},
        ]
        self.rows = []
        for i in range(17):
            row = {'scene_id':f'01/{i+1}', 'shooting_date':f'2026-11-{i+9:02}', 'shooting_day':i+1,
                   'order':1, 'unit':'1st unit', 'location':'TEST', 'characters':'POSTAVA'}
            self.rows.append(row)
            self.cards.append({'id':f'card{i}', 'name':row['scene_id']+'. TEST', 'desc':'Ručné údaje',
                               'idList':'anchor', 'shortUrl':f'https://trello.com/c/{i}', 'due':None,
                               'dueComplete':False, 'pos':i+1})
        self.writes = []

    def get(self, path, params=None):
        if path.startswith('/boards/') and not path.endswith('/lists'):
            return {'id':'board','name':'DOK4','url':'https://trello.com/b/lzNy4AtY','shortLink':'lzNy4AtY'}
        if path.endswith('/lists'):
            return copy.deepcopy(sorted([l for l in self.lists if not l.get('closed')],key=lambda l:l['pos']))
        if path.startswith('/lists/'):
            return copy.deepcopy([c for c in self.cards if c['idList']==path.split('/')[2] and not c.get('closed')])
        raise AssertionError(path)

    def post(self, path, data):
        self.assert_list(path)
        item = dict(data, id='list'+str(len(self.lists)),pos=max(l['pos'] for l in self.lists)+16384)
        self.lists.append(item)
        return copy.deepcopy(item)

    def assert_list(self,path):
        assert path == '/lists',path

    def put(self,path,data):
        self.writes.append((path,dict(data)))
        collection = self.lists if path.startswith('/lists/') else self.cards
        item = next(v for v in collection if v['id']==path.split('/')[-1])
        data = dict(data)
        if data.get('pos') == 'bottom':
            data['pos'] = max(v.get('pos',0) for v in collection)+16384
        elif data.get('pos') == 'top':
            data['pos'] = min(v.get('pos',0) for v in collection)-16384
        item.update(data)
        return copy.deepcopy(item)


class November08PlansTests(unittest.TestCase):
    def test_full_sources_and_remaining_dates(self):
        for filename,count,remaining in [('dok4_schedule_2026-11-08.json',920,49),('riverdale_schedule_2026-11-08.json',229,229)]:
            d=json.loads((ROOT/filename).read_text(encoding='utf-8'))
            self.assertEqual(d['source']['dated'],'2026-11-08')
            self.assertEqual(len(d['rows']),count)
            self.assertEqual(len({r['scene_id'] for r in d['rows']}),count)
            self.assertEqual(sum(r['shooting_date']>='2026-11-09' for r in d['rows']),remaining)
        dok=json.loads((ROOT/'dok4_schedule_2026-11-08.json').read_text(encoding='utf-8'))
        self.assertTrue({'02/45LA','02/45LB'} <= {r['scene_id'] for r in dok['rows']})
        river=json.loads((ROOT/'riverdale_schedule_2026-11-08.json').read_text(encoding='utf-8'))
        self.assertIn('02/8INZ',{r['scene_id'] for r in river['rows']})

    def test_past_dates_preserved_and_seven_plus_ten_order(self):
        t=TrelloFixture()
        before=copy.deepcopy(t.cards[0])
        state=build_state(t,t.rows,'2026-11-08','2026-11-09',preserve_past_dates=True)
        self.assertEqual([c['id'] for c in state['stale_window_cards']],['stale'])
        result=apply(t,state)
        self.assertEqual(result['move_errors_count'],0)
        self.assertEqual(t.cards[0],before)
        stale=next(c for c in t.cards if c['id']=='stale')
        self.assertEqual(stale['idList'],'anchor')
        self.assertEqual(stale['due'],'')
        self.assertFalse(stale['dueComplete'])
        after=summary(build_state(t,t.rows,'2026-11-08','2026-11-09',preserve_past_dates=True),t.rows)
        self.assertEqual(after['window_to_move'],0)
        self.assertEqual(after['window_pending_count'],0)
        self.assertEqual(after['metadata_due_to_update'],0)
        self.assertEqual(after['list_order_pending_count'],0)
        self.assertEqual(len(after['expected_primary_lists']),7)
        self.assertEqual(len(after['expected_tail_lists']),10)

    def test_window_batch_does_not_repeat_unchanged_cards(self):
        t=TrelloFixture()
        state=build_state(t,t.rows,'2026-11-08','2026-11-09',preserve_past_dates=True)
        result=apply(t,state,skip_metadata=True,window_limit=2,cleanup_limit=1)
        self.assertEqual(result['moved_count'],2)
        state=build_state(t,t.rows,'2026-11-08','2026-11-09',preserve_past_dates=True)
        result=apply(t,state,skip_metadata=True,window_limit=2,cleanup_limit=1)
        self.assertEqual(result['moved_count'],2)
        self.assertEqual(summary(build_state(t,t.rows,'2026-11-08','2026-11-09',preserve_past_dates=True),t.rows)['window_pending_count'],13)

    def test_reviewed_working_card_preserves_other_copy(self):
        t=TrelloFixture()
        duplicate=copy.deepcopy(t.cards[2])
        duplicate.update(id='reference',dueComplete=True)
        t.cards.append(duplicate)
        state=build_state(t,t.rows,'2026-11-08','2026-11-09',preserve_past_dates=True,preferred_card_ids={'01/1':'card0'})
        self.assertFalse(state['duplicates'])
        self.assertEqual(state['ignored_reference_duplicates'][0]['selected']['id'],'card0')
        apply(t,state)
        self.assertFalse(next(c for c in t.cards if c['id']=='reference').get('closed'))

    def test_archived_missing_card_is_restored_instead_of_duplicated(self):
        t=TrelloFixture()
        card=t.cards[2]
        card['closed']=True
        original_get=t.get
        def get(path,params=None):
            if path=='/search':
                self.assertIn('is:archived',params['query'])
                return {'cards':[copy.deepcopy(card)]}
            return original_get(path,params)
        t.get=get
        state=build_state(t,t.rows,'2026-11-08','2026-11-09',preserve_past_dates=True)
        self.assertEqual(len(state['missing']),1)
        result=create_missing_placeholders(t,state)
        self.assertEqual(result['created_count'],0)
        self.assertEqual(result['restored_count'],1)
        self.assertFalse(card['closed'])
        self.assertEqual(card['due'],'2026-11-09T10:00:00.000Z')

    def test_rebalanced_positions_are_accepted_when_order_is_correct(self):
        t=TrelloFixture()
        # Three scenes share a date; their nonstandard positions preserve order.
        for i in range(3):
            t.rows[i].update(shooting_date='2026-11-09',order=i+1)
        state=build_state(t,t.rows,'2026-11-08','2026-11-09',preserve_past_dates=True)
        apply(t,state)
        for i in range(3):
            next(c for c in t.cards if c['id']==f'card{i}')['pos']=(i+1)*0.125
        state=build_state(t,t.rows,'2026-11-08','2026-11-09',preserve_past_dates=True)
        self.assertEqual(summary(state,t.rows)['window_pending_count'],0)


if __name__=='__main__':
    unittest.main()
