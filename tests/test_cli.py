import json
import tempfile
import unittest
from pathlib import Path
from repair_agent.cli import main
from repair_agent.evaluate import evaluate_run
from repair_agent.analyze import analyze_rows


class CliTests(unittest.TestCase):
    def test_offline_end_to_end_resume_and_data_change_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'data';run=root/'run'
            main(['generate','--out',str(data),'--count','6','--entities','6','--split','smoke'])
            argv=['run','--data',str(data/'public.jsonl'),'--out',str(run),'--mode','simulate',
                  '--arms','D0,B0,B1,B2,B3','--repeats','2']
            main(argv)
            before=(run/'results.jsonl').read_bytes();main(argv)
            self.assertEqual((run/'results.jsonl').read_bytes(),before)
            main(['evaluate','--run',str(run),'--truth',str(data/'private_truth.jsonl')])
            main(['analyze','--run',str(run)])
            main(['replay','--run',str(run)])
            self.assertTrue((run/'summary.csv').exists());self.assertTrue((run/'comparison.svg').exists())
            summary=json.loads((run/'analysis.json').read_text())
            self.assertIn('SIMULATED',summary['modes'])
            self.assertEqual(summary['total_results'],60)
            manifest=json.loads((run/'manifest.json').read_text())
            self.assertEqual(manifest['network_enabled'],False)
            records=[json.loads(s) for s in (data/'public.jsonl').read_text().splitlines()]
            records[0]['schema']['name']='modified'
            (data/'public.jsonl').write_text(''.join(json.dumps(t)+'\n' for t in records))
            with self.assertRaises(ValueError):main(argv)

    def test_live_requires_flag_and_frozen_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);main(['generate','--out',str(root/'data'),'--count','1'])
            with self.assertRaises(ValueError):main(['run','--data',str(root/'data/public.jsonl'),'--out',str(root/'run'),'--mode','live'])

    def test_incomplete_results_remain_in_denominator(self):
        from test_core import task
        from repair_agent.runner import run_case
        from repair_agent.policies import SimulatedClient
        t=task()
        rows=[run_case(t,'B2',SimulatedClient(),{},0)]
        rows[0]['status']='NETWORK_ERROR';rows[0]['keep_ids']=None
        result=analyze_rows(rows)
        self.assertEqual(result['total_results'],1)
        self.assertEqual(result['groups'][0]['pass_rate'],0)


if __name__=='__main__':unittest.main()
