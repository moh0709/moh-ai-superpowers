"""Malformed JSON-like request objects must be denied rather than crashing."""
from pathlib import Path
import random
import tempfile
import unittest
from frontier.runtime.gate import evaluate_task, verify_completion
from frontier.runtime.score import benchmark


class MalformedContracts(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.root = Path(self.d.name)
        (self.root/'src').mkdir()
        self.valid = dict(task_id='a',objective='safe',base_commit='a'*40,risk='low',
                          operations=[dict(type='write_file',path='src/a.txt')])

    def test_unhashable_risk_denied(self):
        result = evaluate_task({**self.valid,'risk':[]},repo_root=self.root,trusted_scope=frozenset({'src/a.txt'}))
        self.assertFalse(result.allowed)

    def test_unhashable_action_denied(self):
        result = evaluate_task({**self.valid,'operations':[{'type':{},'path':'src/a.txt'}]},
                               repo_root=self.root,trusted_scope=frozenset({'src/a.txt'}))
        self.assertFalse(result.allowed)

    def test_random_json_shapes_fail_closed_without_uncaught_exceptions(self):
        rng = random.Random(42)
        values = [None, [], {}, True, 0, 2.1, '', 'low', 'a'*40,
                  [{'type':'write_file','path':'src/a.txt'}], {'type':[]}]
        for _ in range(300):
            key = rng.choice(list(self.valid))
            value = rng.choice(values)
            request={**self.valid, key:value}
            result=evaluate_task(request, repo_root=self.root, trusted_scope=frozenset())
            self.assertFalse(result.allowed)

    def test_private_keys_denied(self):
        for path in ('.ssh/id_rsa', '.aws/credentials', '.npmrc', '.env.prod',
                     'src/server.pem', '.pypirc', '.git/config'):
            decision=evaluate_task({**self.valid,'operations':[{'type':'read_file','path':path}]},
                                   repo_root=self.root,trusted_scope=frozenset())
            self.assertFalse(decision.allowed,path)

    def test_old_completion_path_fails_closed_without_opt_in(self):
        decision=verify_completion('Verified', {'signature':'a'*64},evidence_root=self.root)
        self.assertFalse(decision.allowed)
        self.assertIn('legacy_evidence_disabled',decision.reasons)

    def test_benchmark_malformed_arm_rejected(self):
        with self.assertRaises(ValueError):
            benchmark([{'task_id':'a','trial_index':0,'arm':[],
                        'success':True,'cost_usd':1,'safety_violation':False}])

    def test_benchmark_boolean_cost_rejected(self):
        with self.assertRaises(ValueError):
            benchmark([{'task_id':'a','trial_index':0,'arm':'candidate',
                        'success':True,'cost_usd':True,'safety_violation':False}])

    def test_invalid_bootstrap_size(self):
        with self.assertRaises(ValueError): benchmark([],bootstrap_samples=0)


if __name__=='__main__':unittest.main()
