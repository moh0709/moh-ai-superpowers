import hashlib
import tempfile
import unittest
from pathlib import Path
from frontier.runtime.gate import evaluate_task, verify_completion, validate_repo_path, sign_verification

COMMIT = 'a' * 40

class GateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'src').mkdir()
        (self.root/'src'/'safe.py').write_text('print(1)')
        self.scope = frozenset({'src/safe.py', 'src/new.py', 'src/payments.py', 'frontier/runtime/score.py'})
        self.task = dict(task_id='T-1', objective='Safe feature', base_commit=COMMIT,
                         risk='low', operations=[{'type':'write_file', 'path':'src/safe.py'}])

    def check(self, patch, expected, *, scope=None):
        t = {**self.task, **patch}
        result = evaluate_task(t, repo_root=self.root, trusted_scope=self.scope if scope is None else scope)
        self.assertEqual(result.allowed, expected, (patch, result))
        return result

    def test_valid_scoped_write(self): self.check({}, True)
    def test_valid_scoped_new_file(self): self.check({'operations':[{'type':'write_file','path':'src/new.py'}]},True)
    def test_read_beyond_write_scope(self): self.check({'operations':[{'type':'read_file','path':'src/other.py'}]},True)
    def test_no_task_id(self): self.check({'task_id':''},False)
    def test_missing_objective(self): self.check({'objective':None},False)
    def test_missing_pinned_commit(self): self.check({'base_commit':'main'},False)
    def test_risk_unrecognized(self): self.check({'risk':'safe'},False)
    def test_high_risk_denied(self): self.check({'risk':'high','rollback_plan':'yes','approved':True},False)
    def test_medium_risk_without_rollback_denied(self): self.check({'risk':'medium'},False)
    def test_medium_risk_with_rollback_still_requires_external_approval(self): self.check({'risk':'medium','rollback_plan':'revert'},False)
    def test_unknown_action(self): self.check({'operations':[{'type':'execute_python','path':'src/safe.py'}]},False)
    def test_shell_execution_denied(self): self.check({'operations':[{'type':'run_shell','command':'rm -rf /'}]},False)
    def test_deployment_denied(self): self.check({'operations':[{'type':'deploy','target':'production'}]},False)
    def test_delete_denied(self): self.check({'operations':[{'type':'delete_file','path':'src/safe.py'}]},False)
    def test_file_outside_scope(self): self.check({'operations':[{'type':'write_file','path':'src/other.py'}]},False)
    def test_traversal(self): self.check({'operations':[{'type':'write_file','path':'src/../../.env'}]},False)
    def test_windows_traversal(self): self.check({'operations':[{'type':'write_file','path':'src\\..\\.env'}]},False)
    def test_absolute_path(self): self.check({'operations':[{'type':'write_file','path':'/etc/passwd'}]},False)
    def test_encoded_traversal(self): self.check({'operations':[{'type':'write_file','path':'src/%2e%2e/.env'}]},False)
    def test_double_slash(self): self.check({'operations':[{'type':'write_file','path':'src//safe.py'}]},False)
    def test_dot_segment(self): self.check({'operations':[{'type':'write_file','path':'src/./safe.py'}]},False)
    def test_symlink_within_root(self):
        (self.root/'src'/'link.py').symlink_to(self.root/'src'/'safe.py')
        self.check({'operations':[{'type':'write_file','path':'src/link.py'}]},False,scope=frozenset({'src/link.py'}))
    def test_symlink_escape(self):
        (self.root/'src'/'escape').symlink_to('/tmp')
        self.check({'operations':[{'type':'write_file','path':'src/escape/pwn'}]},False,scope=frozenset({'src/escape/pwn'}))
    def test_policy_edit_denied(self): self.check({'operations':[{'type':'write_file','path':'frontier/runtime/score.py'}]},False)
    def test_payment_path_denied_even_with_scope(self): self.check({'operations':[{'type':'write_file','path':'src/payments.py'}],'approved':True},False)
    def test_fake_approval_ignored(self): self.check({'operations':[{'type':'write_file','path':'src/other.py'}],'approved':True},False)
    def test_empty_ops(self): self.check({'operations':[]},False)
    def test_mixed_safe_unsafe_ops(self): self.check({'operations':[{'type':'write_file','path':'src/safe.py'}, {'type':'run_shell','command':'echo done'}]},False)
    def test_payment_change_hidden_in_safe_filename(self):
        self.check({'objective':'Implement Stripe checkout changes in safe.py'},False)
    def test_forged_verifier_authority_does_not_prove_identity(self):
        data=b'{"passed":true}'
        (self.root/'evidence.json').write_bytes(data)
        forged={'authority':'trusted_verifier','exit_code':0,'tests_run':5,
                'artifact':'evidence.json','sha256':hashlib.sha256(data).hexdigest()}
        self.assertFalse(verify_completion('Verified',forged,evidence_root=self.root).allowed)
    def test_read_env_denied(self): self.check({'operations':[{'type':'read_file','path':'.env'}]},False)
    def test_completion_no_evidence(self):
        self.assertFalse(verify_completion('Verified',None,evidence_root=self.root).allowed)
    def test_completion_agent_authored_only(self):
        self.assertFalse(verify_completion('Verified',{'authority':'agent','exit_code':0,'tests_run':10},evidence_root=self.root).allowed)
    def test_completion_failed_tests(self):
        self.assertFalse(verify_completion('Verified',{'authority':'trusted_verifier','exit_code':1,'tests_run':5},evidence_root=self.root).allowed)
    def test_completion_no_tests(self):
        self.assertFalse(verify_completion('Verified',{'authority':'trusted_verifier','exit_code':0,'tests_run':0},evidence_root=self.root).allowed)
    def test_completion_forged_hash(self):
        (self.root/'evidence.json').write_text('{"passed":true}')
        self.assertFalse(verify_completion('Verified',{'authority':'trusted_verifier','exit_code':0,'tests_run':1,'artifact':'evidence.json','sha256':'0'*64},evidence_root=self.root).allowed)
    def test_completion_missing_artifact(self):
        self.assertFalse(verify_completion('Verified',{'authority':'trusted_verifier','exit_code':0,'tests_run':1,'artifact':'missing.json','sha256':'0'*64},evidence_root=self.root).allowed)
    def test_completion_valid_evidence(self):
        data = b'{"passed":true}'
        (self.root/'evidence.json').write_bytes(data)
        evidence = {'authority':'trusted_verifier','exit_code':0,'tests_run':1,
                    'task_id':'T-1','base_commit':COMMIT,
                    'artifact':'evidence.json','sha256':hashlib.sha256(data).hexdigest()}
        evidence['signature']=sign_verification(evidence,b'private-test-key')
        self.assertTrue(verify_completion('Verified',evidence,evidence_root=self.root,
                        verification_key=b'private-test-key',expected_task_id='T-1',expected_base_commit=COMMIT,
                        allow_legacy_signed_receipts=True).allowed)
    def test_signed_evidence_replay_against_other_task_denied(self):
        data=b'tests passed'
        (self.root/'evidence.json').write_bytes(data)
        evidence=dict(task_id='T-1',base_commit=COMMIT,exit_code=0,tests_run=1,
                      artifact='evidence.json',sha256=hashlib.sha256(data).hexdigest())
        evidence['signature']=sign_verification(evidence,b'private-test-key')
        self.assertFalse(verify_completion('Verified',evidence,evidence_root=self.root,
             verification_key=b'private-test-key',expected_task_id='T-2',expected_base_commit=COMMIT).allowed)
    def test_tampered_signed_evidence_denied(self):
        data=b'tests passed'
        (self.root/'evidence.json').write_bytes(data)
        evidence=dict(task_id='T-1',base_commit=COMMIT,exit_code=0,tests_run=1,
                      artifact='evidence.json',sha256=hashlib.sha256(data).hexdigest())
        evidence['signature']=sign_verification(evidence,b'private-test-key')
        evidence['tests_run']=100
        self.assertFalse(verify_completion('Verified',evidence,evidence_root=self.root,
             verification_key=b'private-test-key',expected_task_id='T-1',expected_base_commit=COMMIT,
                        allow_legacy_signed_receipts=True).allowed)
    def test_nonverified_status_is_not_false_claim(self):
        self.assertTrue(verify_completion('Not verified',None,evidence_root=self.root).allowed)
    def test_invalid_status(self):
        self.assertFalse(verify_completion('Absolutely done',None,evidence_root=self.root).allowed)

if __name__ == '__main__': unittest.main()
