import copy
import itertools
import json
import tempfile
import unittest
from pathlib import Path

from repair_agent.domain import validate_task, parse_candidate, task_hash
from repair_agent.data_builder import generate_dataset, generate_paired_dataset, load_tasks
from repair_agent.checker import diagnose, decision, exhaustive_optimum
from repair_agent.legacy import verify_snapshot, IncrementalSession


def task():
    return dict(task_id='x', base_instance_id='base', split='test',
                schema=dict(name='R', attributes=['A','B'],
                            fds=[dict(lhs=['A'],rhs=['B']),dict(lhs=['B'],rhs=['A'])]),
                records=[dict(id='x1',values=['a1','b1']),dict(id='x2',values=['a1','b2']),
                         dict(id='x3',values=['a2','b2'])],
                initial_keep_ids=['x2'],source_evidence={})


class CoreTests(unittest.TestCase):
    def test_paired_dataset_shares_base_table_and_hidden_truth(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)/'paired'
            manifest=generate_paired_dataset(base,15,2026102301,'test',8)
            public=load_tasks(base/'public.jsonl')
            private=[json.loads(line) for line in (base/'private_truth.jsonl').read_text().splitlines()]
            self.assertEqual(len(public),30)
            self.assertEqual(manifest['pairs'],15)
            by_base={}
            for row in public: by_base.setdefault(row['base_instance_id'],[]).append(row)
            truth={row['task_id']:row for row in private}
            self.assertEqual(len(by_base),15)
            for pair in by_base.values():
                self.assertEqual({row['track'] for row in pair},{'C0','C1'})
                left,right=sorted(pair,key=lambda row:row['track'])
                for key in ('schema','records','initial_keep_ids','category','family'):
                    self.assertEqual(left[key],right[key])
                self.assertEqual(left['source_evidence'],{})
                self.assertTrue(right['source_evidence'])
                self.assertEqual(truth[left['task_id']]['true_ids'],truth[right['task_id']]['true_ids'])
            cells={(row['family'],row['category'],row['track']) for row in public}
            self.assertEqual(len(cells),30)

    def test_every_subset_matches_definition_and_legacy(self):
        t=validate_task(task())
        for mask in itertools.product([False,True],repeat=3):
            ids=[r['id'] for r,b in zip(t['records'],mask) if b]
            diag=diagnose(t,ids)
            expected=not diag['conflicts'] and not diag['addable_ids']
            self.assertEqual(decision(t,ids,'generic')['is_repair'],expected)
            self.assertEqual(decision(t,ids,'bcnf')['is_repair'],expected)
        self.assertTrue(decision(t,['x2'])['is_repair'])
        self.assertEqual(exhaustive_optimum(t)['maximum_size'],2)

    def test_strict_ids_and_schema(self):
        t=task()
        for output in ['{"keep_ids":["bad"]}','{"keep_ids":["x1","x1"]}',
                       '{"keep_ids":[1]}','[]','prefix\n```json\n{"keep_ids":[]}\n```',
                       '```json\n{"keep_ids":[]}\n```\nsuffix',
                       '```json\n{"keep_ids":[]}\n```\n```json\n{"keep_ids":[]}\n```']:
            with self.assertRaises(ValueError): parse_candidate(output,t)
        self.assertEqual(parse_candidate('{"keep_ids":[]}',t),[])
        self.assertEqual(parse_candidate('```json\n{"keep_ids":[]}\n```',t),[])
        self.assertEqual(parse_candidate('  ```JSON\r\n{"keep_ids":["x2"]}\r\n```  ',t),['x2'])
        for change in ['null','duplicate','hidden']:
            v=copy.deepcopy(t)
            if change=='null': v['records'][0]['values'][0]=None
            elif change=='duplicate': v['records'].append(copy.deepcopy(v['records'][0]))
            else: v['true_ids']=['x1']
            with self.assertRaises(ValueError): validate_task(v)

    def test_non_bcnf_is_only_generic(self):
        t=task(); t['schema']['attributes'].append('C')
        for r in t['records']: r['values'].append(r['id'])
        validate_task(t)
        self.assertFalse(decision(t,[])['is_repair'])
        with self.assertRaises(ValueError): decision(t,[],'bcnf')

    def test_no_fds_and_empty_database(self):
        t=task(); t['schema']['fds']=[]
        self.assertFalse(decision(t,[],'bcnf')['is_repair'])
        self.assertTrue(decision(t,['x1','x2','x3'],'bcnf')['is_repair'])
        t['records']=[]; t['initial_keep_ids']=[]
        self.assertTrue(decision(t,[],'bcnf')['is_repair'])

    def test_incremental_handles_inconsistent_intermediate_states(self):
        t=task(); session=IncrementalSession(t)
        for ids in [[],['x1'],['x1','x2'],['x1','x3'],['x2'],['x1','x2','x3'],[]]:
            self.assertEqual(session.update(ids)['is_repair'],decision(t,ids)['is_repair'])
        self.assertTrue(verify_snapshot()['ok'])

    def test_datasets_are_frozen_public_and_balanced(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)/'data'
            manifest=generate_dataset(base,60,42,'test')
            public=load_tasks(base/'public.jsonl')
            self.assertEqual(len(public),60)
            self.assertEqual(len({t['base_instance_id'] for t in public}),60)
            self.assertEqual(len({t['task_id'] for t in public}),60)
            for t in public:
                validate_task(t)
                self.assertNotIn('true_ids',json.dumps(t))
                decision(t,t['initial_keep_ids'],'bcnf')
            with self.assertRaises(FileExistsError): generate_dataset(base,60,42,'test')
            other=Path(temp)/'other'
            generate_dataset(other,60,42,'test')
            self.assertEqual((base/'public.jsonl').read_bytes(),(other/'public.jsonl').read_bytes())
            self.assertEqual(manifest['count'],60)
            private=[json.loads(line) for line in (base/'private_truth.jsonl').read_text().splitlines()]
            truth={r['task_id']:r for r in private}
            for t in public:
                self.assertTrue(decision(t,truth[t['task_id']]['true_ids'])['consistent'])
            train=Path(temp)/'dev';generate_dataset(train,60,42,'dev')
            self.assertTrue({t['base_instance_id'] for t in public}.isdisjoint(
                {t['base_instance_id'] for t in load_tasks(train/'public.jsonl')}))


if __name__=='__main__': unittest.main()
