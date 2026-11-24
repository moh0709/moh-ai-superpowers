"""End-to-end local fixture tests; no live AI agent and no OS sandbox."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from frontier.runtime.controller import OperationDenied, ScopedController
from frontier.runtime.evidence_v2 import ReplayStore, verify_receipt
from frontier.runtime.verifier import TestProfile, TrustedTestExecutor, scope_digest


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@unittest.skipUnless(os.name == 'posix', 'POSIX scoped controller required')
class EndToEndLocalTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.tmp = Path(self.d.name)
        self.workspace = self.tmp / 'workspace'
        self.workspace.mkdir()
        self.evidence = self.tmp / 'evidence'
        self.evidence.mkdir()
        (self.workspace / 'src').mkdir()
        (self.workspace / 'tests').mkdir()
        (self.workspace / 'src' / 'safe.py').write_text('print(1)\n')
        (self.workspace / 'tests' / 'test_sample.py').write_text(
            "import unittest\nfrom pathlib import Path\n"
            "class TestSample(unittest.TestCase):\n"
            "    def test_expected_content(self):\n"
            "        self.assertEqual((Path('src')/'safe.py').read_text(), 'print(2)\\n')\n")
        git(self.workspace, 'init', '-q')
        git(self.workspace, 'add', '.')
        git(self.workspace, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            'commit', '-qm', 'initial')
        self.commit = git(self.workspace, 'rev-parse', 'HEAD')
        self.scope = frozenset({'src/safe.py'})
        self.key = b'controller-held-key-material-over-32-bytes'
        self.profile = TestProfile('unittest', (sys.executable, '-m', 'unittest',
                                                'discover', '-s', 'tests', '-q'))
        self.runner = TrustedTestExecutor(self.workspace, self.evidence, signer_key=self.key,
                                          issuer='controller', profiles=(self.profile,))
        self.replay = ReplayStore(self.tmp / 'replay.db')

    def run_test(self, name):
        return self.runner.run(profile_id='unittest', task_id='task-1',
                               base_commit=self.commit, run_id=name, scoped_paths=self.scope)

    def verify(self, receipt):
        return verify_receipt(receipt, key=self.key, issuer='controller', task_id='task-1',
                              base_commit=self.commit,
                              workspace_digest=scope_digest(self.workspace, self.scope),
                              evidence_root=self.evidence, replay_store=self.replay)

    def test_passing_write_is_verified_only_after_real_tests(self):
        ctl = ScopedController(self.workspace, self.scope)
        digest = hashlib.sha256(b'print(1)\n').hexdigest()
        task = {'task_id':'task-1', 'objective':'Change harmless example',
                'base_commit':self.commit, 'risk':'low', 'operations':[
                    {'type':'write_file', 'path':'src/safe.py', 'content':'print(2)\n',
                     'expected_sha256':digest}]}
        write = ctl.write(task,dry_run=False)
        self.assertEqual(write.verification_status,'Not verified')
        receipt = self.run_test('passing-run')
        self.assertEqual(receipt['tests_run'],1)
        self.assertTrue(self.verify(receipt).allowed)
        self.assertIn('replayed_receipt',self.verify(receipt).reasons)

    def test_unmodified_failing_test_is_not_verified(self):
        receipt=self.run_test('failing-run')
        self.assertEqual(receipt['tests_run'],1)
        self.assertEqual(receipt['exit_code'],1)
        self.assertIn('tests_not_passing',self.verify(receipt).reasons)

    def test_empty_scope_cannot_prove_success(self):
        with self.assertRaises(OperationDenied) as ctx:
            self.runner.run(profile_id='unittest',task_id='task-1',base_commit=self.commit,
                            run_id='empty-scope',scoped_paths=frozenset())
        self.assertIn('empty_digest_scope',ctx.exception.reasons)

    def test_missing_profile_cannot_run(self):
        with self.assertRaises(OperationDenied) as ctx:
            self.runner.run(profile_id='shell',task_id='task-1',base_commit=self.commit,
                            run_id='command-run',scoped_paths=self.scope)
        self.assertIn('unknown_test_profile',ctx.exception.reasons)

    def test_evidence_root_in_workspace_rejected(self):
        (self.workspace/'evidence').mkdir()
        with self.assertRaises(OperationDenied) as ctx:
            TrustedTestExecutor(self.workspace,self.workspace/'evidence',signer_key=self.key,
                                issuer='controller',profiles=(self.profile,))
        self.assertIn('evidence_must_be_outside_workspace',ctx.exception.reasons)

    def test_duplicate_run_artifact_rejected(self):
        self.run_test('same-name')
        with self.assertRaises(OperationDenied) as ctx:
            self.run_test('same-name')
        self.assertIn('duplicate_run_id',ctx.exception.reasons)

    def test_scope_changed_by_test_is_not_verified(self):
        (self.workspace/'tests/test_sample.py').write_text(
            "import unittest\nfrom pathlib import Path\n"
            "class TestSample(unittest.TestCase):\n"
            "    def test_changes_file(self):\n"
            "        (Path('src')/'safe.py').write_text('hijacked')\n"
            "        self.assertTrue(True)\n")
        receipt=self.run_test('mutating-test')
        self.assertEqual(receipt['exit_code'],125)
        self.assertIn('binding_mismatch',self.verify(receipt).reasons)
        self.assertIn('tests_not_passing', verify_receipt(
            receipt, key=self.key, issuer='controller', task_id='task-1',
            base_commit=self.commit, workspace_digest=receipt['workspace_digest'],
            evidence_root=self.evidence, replay_store=self.replay).reasons)

    def test_workspace_hash_mismatch_after_receipt_rejected(self):
        receipt=self.run_test('failing-but-signed')
        (self.workspace/'src/safe.py').write_text('new different content')
        self.assertIn('binding_mismatch',self.verify(receipt).reasons)


if __name__=='__main__': unittest.main()
