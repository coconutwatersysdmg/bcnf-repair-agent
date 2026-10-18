import json
import unittest
from test_core import task
from repair_agent.feedback import make_feedback
from repair_agent.runner import run_case, first_messages
from repair_agent.policies import SimulatedClient, ScriptedClient


class RunnerTests(unittest.TestCase):
    def test_boolean_feedback_has_no_witness(self):
        t=task()
        text=make_feedback(t,['x1','x2'],'B1',200)
        self.assertNotIn('x1',text); self.assertNotIn('conflict',text)
        self.assertEqual(json.loads(text)['status'],'FAIL')

    def test_budget_is_exact_utf8_bytes_and_full_has_overflow(self):
        t=task();t['records'][0]['values'][0]='汉字'
        t['records'][1]['values'][0]='汉字'
        full=make_feedback(t,['x1','x2'],'B2',1)
        for arm in ['B3','B3_truncate','B3_random']:
            text=make_feedback(t,['x1','x2'],arm,120)
            self.assertLessEqual(len(text.encode('utf-8')),120)
            json.loads(text)
        self.assertIn('conflict',full)
        with self.assertRaises(ValueError): make_feedback(t,[],'B3',1)

    def test_first_prompt_same_and_cannot_accept_truth(self):
        t=task();messages=first_messages(t)
        self.assertNotIn('true_ids',json.dumps(messages))
        t['true_ids']=['x1']
        with self.assertRaises(ValueError): first_messages(t)

    def test_invalid_id_is_not_silently_repaired(self):
        c=ScriptedClient(['{"keep_ids":["bad"]}'])
        result=run_case(task(),'B0',c,{},0)
        self.assertEqual(result['status'],'INVALID_OUTPUT')
        self.assertIsNone(result['keep_ids'])
        self.assertEqual(len(result['trajectory']),1)

    def test_success_loop_and_repeat_status(self):
        c=ScriptedClient(['{"keep_ids":["x1","x2"]}','{"keep_ids":["x1","x3"]}'])
        result=run_case(task(),'B2',c,{},0)
        self.assertEqual(result['status'],'PASS')
        self.assertEqual(result['rounds'],2)
        self.assertIn('conflict',c.requests[1][-1]['content'])
        c=ScriptedClient(['{"keep_ids":[]}']*5)
        result=run_case(task(),'B1',c,{},0)
        self.assertEqual(result['status'],'REPEATED_STATE')

    def test_simulated_results_marked_and_deterministic_baseline(self):
        c=SimulatedClient()
        result=run_case(task(),'B2',c,{},0)
        self.assertEqual(result['mode'],'SIMULATED')
        self.assertEqual(result['status'],'PASS')
        result=run_case(task(),'D0',None,{},0)
        self.assertEqual(result['mode'],'DETERMINISTIC')
        self.assertEqual(result['status'],'PASS')

    def test_context_cap_and_last_invalid_round(self):
        result=run_case(task(),'B2',ScriptedClient([]),{'input_byte_cap':10},0)
        self.assertEqual(result['status'],'CONTEXT_LIMIT')
        result=run_case(task(),'B1',ScriptedClient(['not json']*5),{'max_rounds':2},0)
        self.assertEqual(result['status'],'INVALID_OUTPUT')
        self.assertEqual(result['rounds'],2)


if __name__=='__main__':unittest.main()
