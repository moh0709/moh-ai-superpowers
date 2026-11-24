import hashlib
from pathlib import Path
import tempfile
import unittest

from frontier.runtime.evidence_v2 import ReplayStore, issue_receipt, verify_receipt


class EvidenceV2Tests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.root = Path(self.d.name)
        (self.root / 'results').mkdir()
        self.payload = b'Ran 4 tests in 0.1s\nOK\n'
        (self.root / 'results' / 'run.log').write_bytes(self.payload)
        self.key = b'key-owned-by-test-controller-32bytes!'
        self.commit = 'a' * 40
        self.workspace = 'b' * 64
        self.store = ReplayStore(self.root / 'controller-state' / 'used.sqlite')

    def receipt(self, **changes):
        args = dict(key=self.key, issuer='host-verifier', task_id='t1',
                    base_commit=self.commit, workspace_digest=self.workspace,
                    run_id='run-1', artifact='results/run.log',
                    sha256=hashlib.sha256(self.payload).hexdigest(),
                    exit_code=0, tests_run=4, command_id='unit', now=10000)
        args.update(changes)
        return issue_receipt(**args)

    def verify(self, receipt, **changes):
        args = dict(key=self.key, issuer='host-verifier', task_id='t1',
                    base_commit=self.commit, workspace_digest=self.workspace,
                    evidence_root=self.root, replay_store=self.store, now=10010)
        args.update(changes)
        return verify_receipt(receipt, **args)

    def test_valid_once(self):
        self.assertTrue(self.verify(self.receipt()).allowed)

    def test_replay_rejected(self):
        receipt = self.receipt()
        self.assertTrue(self.verify(receipt).allowed)
        self.assertIn('replayed_receipt', self.verify(receipt).reasons)

    def test_replay_persists_across_connections(self):
        receipt = self.receipt()
        self.assertTrue(self.verify(receipt).allowed)
        self.store = ReplayStore(self.root / 'controller-state' / 'used.sqlite')
        self.assertFalse(self.verify(receipt).allowed)

    def test_wrong_task_rejected(self):
        self.assertIn('binding_mismatch', self.verify(self.receipt(),task_id='t2').reasons)

    def test_wrong_commit_rejected(self):
        self.assertIn('binding_mismatch', self.verify(self.receipt(),base_commit='f'*40).reasons)

    def test_wrong_workspace_rejected(self):
        self.assertIn('binding_mismatch', self.verify(self.receipt(),workspace_digest='a'*64).reasons)

    def test_wrong_issuer_rejected(self):
        self.assertIn('binding_mismatch', self.verify(self.receipt(),issuer='fake').reasons)

    def test_bad_signature_rejected(self):
        r=self.receipt();r['signature']='0'*64
        self.assertIn('invalid_signature',self.verify(r).reasons)

    def test_unsigned_field_added_rejected(self):
        r=self.receipt();r['agent_says_approved']=True
        self.assertIn('invalid_receipt',self.verify(r).reasons)

    def test_tampered_test_count_rejected(self):
        r=self.receipt();r['tests_run']=999
        self.assertIn('invalid_signature',self.verify(r).reasons)

    def test_missing_signature_rejected(self):
        r=self.receipt();r.pop('signature')
        self.assertIn('invalid_signature',self.verify(r).reasons)

    def test_short_key_rejected(self):
        with self.assertRaises(ValueError): self.receipt(key=b'weak')

    def test_wrong_key_rejected(self):
        self.assertIn('invalid_signature',self.verify(self.receipt(),key=b'x'*32).reasons)

    def test_artifact_change_detected(self):
        r=self.receipt()
        (self.root/'results/run.log').write_text('modified')
        self.assertIn('artifact_digest_mismatch',self.verify(r).reasons)

    def test_symlink_artifact_rejected(self):
        (self.root/'results/run.log').unlink()
        (self.root/'results/run.log').symlink_to('/etc/passwd')
        self.assertIn('invalid_artifact_path',self.verify(self.receipt()).reasons)

    def test_expired_rejected(self):
        self.assertIn('expired_or_future_receipt',self.verify(self.receipt(),now=10600).reasons)

    def test_future_issued_rejected(self):
        self.assertIn('expired_or_future_receipt',self.verify(self.receipt(now=12000)).reasons)

    def test_no_tests_is_not_verified(self):
        self.assertIn('tests_not_passing',self.verify(self.receipt(tests_run=0)).reasons)

    def test_failed_command_is_not_verified(self):
        self.assertIn('tests_not_passing',self.verify(self.receipt(exit_code=1)).reasons)

    def test_boolean_test_count_rejected(self):
        with self.assertRaises(ValueError): self.receipt(tests_run=True)

    def test_long_lifetime_rejected(self):
        with self.assertRaises(ValueError): self.receipt(lifetime_seconds=601)

    def test_duplicate_run_id_with_different_nonce_rejected(self):
        first=self.receipt(); second=self.receipt()
        self.assertTrue(self.verify(first).allowed)
        self.assertIn('replayed_receipt',self.verify(second).reasons)

    def test_missing_artifact_rejected(self):
        (self.root/'results/run.log').unlink()
        self.assertIn('artifact_unavailable',self.verify(self.receipt()).reasons)

    def test_path_traversal_rejected(self):
        r=self.receipt(artifact='../escape')
        self.assertIn('invalid_artifact_path',self.verify(r).reasons)

    def test_artifact_size_limit(self):
        r=self.receipt()
        (self.root/'results/run.log').write_bytes(b'x'*(1024*1024+1))
        self.assertIn('artifact_too_large',self.verify(r).reasons)

    def test_malformed_receipt_rejected(self):
        self.assertIn('missing_receipt',self.verify(None).reasons)


if __name__=='__main__': unittest.main()
