import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_core import task
from repair_agent.run_io import append_jsonl, read_jsonl
from repair_agent.budget_cache import Store
from repair_agent.model_client import ModelClient
from repair_agent.config import defaults
from repair_agent.runner import run_case
from repair_agent.data_builder import generate_dataset, load_tasks


class RecoveryTests(unittest.TestCase):
    def test_non_bcnf_replay_has_explicit_skipped_status(self):
        from repair_agent.replay import replay_run
        t=task();t['schema']['attributes'].append('C')
        for row in t['records']:row['values'].append(row['id'])
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)
            append_jsonl(path/'public_tasks.jsonl',t)
            append_jsonl(path/'results.jsonl',dict(task_id='x',arm='B0',repeat=0,keep_ids=['x2']))
            result=replay_run(path)
            self.assertEqual(result['skipped_non_bcnf_results'],1)
            self.assertIsNone(result['all_backends_agree'])

    def test_crash_reconstruction_attributes_cached_original_cost(self):
        transport=lambda *args:dict(choices=[dict(message=dict(content='{"keep_ids":["x2"]}'),finish_reason='stop')],
                                    usage=dict(prompt_tokens=100,completion_tokens=20))
        with tempfile.TemporaryDirectory() as temp:
            with Store(Path(temp)/'book.db',20,1000) as book:
                client=ModelClient(defaults(),book,transport)
                with patch.dict(os.environ,{'DASHSCOPE_API_KEY':'secret'}):
                    first=run_case(task(),'B0',client,defaults(),0)
                    recovered=run_case(task(),'B0',client,defaults(),0)
                self.assertEqual(first['billed_cny'],recovered['billed_cny'])
                self.assertEqual(recovered['network_attempts'],1)
                self.assertEqual(book.summary()['attempts'],1)
                self.assertEqual(recovered['cached_calls'],1)

    def test_public_values_have_identical_opaque_format(self):
        import re
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'data';generate_dataset(path,30,42,'dev',8)
            for item in load_tasks(path/'public.jsonl'):
                for row in item['records']:
                    for value in row['values']:
                        self.assertRegex(value,r'^v[0-9a-f]{16}$')

    def test_valid_tail_without_newline_remains_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'rows.jsonl';path.write_bytes(b'{"a":1}')
            self.assertEqual(read_jsonl(path,repair_tail=True),[{'a':1}])
            append_jsonl(path,{'a':2})
            self.assertEqual(read_jsonl(path),[{'a':1},{'a':2}])

    def test_network_failure_keeps_cost_in_case_and_ledger(self):
        def fail(*args):raise TimeoutError('secret never logged')
        with tempfile.TemporaryDirectory() as temp:
            with Store(Path(temp)/'book.db',20,1000) as book:
                client=ModelClient(defaults(),book,fail)
                with patch.dict(os.environ,{'DASHSCOPE_API_KEY':'secret'}):
                    result=run_case(task(),'B2',client,defaults(),0)
                self.assertEqual(result['status'],'NETWORK_ERROR')
                self.assertEqual(result['network_attempts'],1)
                self.assertEqual(result['billed_cny'],book.summary()['cost_cny'])
                self.assertGreater(result['billed_cny'],0)
