"""Small exhaustive checks against the mathematical pairwise FD definition."""
import itertools
import random
import unittest
from repair_agent.domain import validate_task,is_bcnf
from repair_agent.checker import decision,diagnose
from repair_agent.legacy import IncrementalSession


class OracleTests(unittest.TestCase):
    def test_random_fds_all_subsets_match_pairwise_definition(self):
        rng=random.Random(130)
        for sample in range(30):
            attrs=['A','B','C']
            fds=[dict(lhs=rng.sample(attrs,rng.randrange(4)),rhs=rng.sample(attrs,rng.randrange(4)))
                 for _ in range(rng.randrange(4))]
            if sample%3==0:
                fds=[dict(lhs=rng.sample(attrs,rng.randrange(3)),rhs=attrs[:])]
            tuples=rng.sample(list(itertools.product('012',repeat=3)),6)
            task=dict(task_id=str(sample),base_instance_id=str(sample),split='test',
                      schema=dict(name='R',attributes=attrs,fds=fds),
                      records=[dict(id=str(i),values=list(t)) for i,t in enumerate(tuples)],
                      initial_keep_ids=[],source_evidence={})
            validate_task(task)
            positions={a:i for i,a in enumerate(attrs)}
            def consistent(indices):
                for i,j in itertools.combinations(indices,2):
                    for fd in fds:
                        if all(tuples[i][positions[a]]==tuples[j][positions[a]] for a in fd['lhs']):
                            if any(tuples[i][positions[a]]!=tuples[j][positions[a]] for a in fd['rhs']):return False
                return True
            session=IncrementalSession(task) if is_bcnf(task['schema']) else None
            for bits in itertools.product((False,True),repeat=6):
                indices=[i for i,b in enumerate(bits) if b];ids=list(map(str,indices))
                ok=consistent(indices)
                maximal=ok and all(not consistent(indices+[i]) for i in range(6) if i not in indices)
                expected=dict(consistent=ok,is_repair=maximal)
                self.assertEqual(decision(task,ids),expected)
                diag=diagnose(task,ids)
                self.assertEqual((diag['consistent'],diag['is_repair']),(ok,maximal))
                if session:
                    self.assertEqual(decision(task,ids,'bcnf'),expected)
                    actual=session.update(ids)
                    self.assertEqual((actual['consistent'],actual['is_repair']),(ok,maximal))
