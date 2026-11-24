import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from frontier.runtime.controller import ScopedController, OperationDenied
from frontier.runtime.gate import evaluate_task


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@unittest.skipUnless(os.name == 'posix', 'descriptor-relative write test requires POSIX')
class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.root = Path(self.d.name)
        (self.root / 'src').mkdir()
        (self.root / 'src' / 'safe.py').write_text('print(1)\n')
        git(self.root, 'init', '-q')
        git(self.root, 'add', 'src/safe.py')
        git(self.root, '-c', 'user.name=Test', '-c', 'user.email=fixture@example.invalid',
            'commit', '-qm', 'fixture')
        self.commit = git(self.root, 'rev-parse', 'HEAD')
        self.controller = ScopedController(self.root, frozenset({'src/safe.py', 'src/new.py', 'src/escape.py'}))
        self.task = self.make_task()

    def make_task(self, path='src/safe.py', content='print(2)\n', expected='auto'):
        if expected == 'auto':
            expected = hashlib.sha256(b'print(1)\n').hexdigest()
        return {
            'task_id': 'task-1', 'objective': 'Change a harmless example',
            'base_commit': self.commit, 'risk': 'low',
            'operations': [{'type': 'write_file', 'path': path,
                            'content': content, 'expected_sha256': expected}],
        }

    def assert_denied(self, task, reason):
        with self.assertRaises(OperationDenied) as ctx:
            self.controller.write(task, dry_run=False)
        self.assertIn(reason, ctx.exception.reasons)

    def test_dry_run_does_not_mutate(self):
        r = self.controller.write(self.task)
        self.assertFalse(r.applied)
        self.assertEqual(r.verification_status, 'Not verified')
        self.assertEqual((self.root / 'src/safe.py').read_text(), 'print(1)\n')

    def test_write_executes_only_scoped_change(self):
        r = self.controller.write(self.task, dry_run=False)
        self.assertTrue(r.applied)
        self.assertEqual(r.verification_status, 'Not verified')
        self.assertEqual((self.root / 'src/safe.py').read_text(), 'print(2)\n')
        self.assertEqual(r.after_sha256, hashlib.sha256(b'print(2)\n').hexdigest())

    def test_stale_digest_blocks(self):
        self.task['operations'][0]['expected_sha256'] = '0' * 64
        self.assert_denied(self.task, 'unexpected_existing_contents')
        self.assertEqual((self.root / 'src/safe.py').read_text(), 'print(1)\n')

    def test_stale_after_dry_run_blocks(self):
        self.controller.write(self.task)
        (self.root / 'src/safe.py').write_text('changed externally\n')
        self.assert_denied(self.task, 'unexpected_existing_contents')

    def test_missing_existing_digest_blocks(self):
        self.task['operations'][0]['expected_sha256'] = None
        self.assert_denied(self.task, 'unexpected_existing_contents')

    def test_wrong_commit_blocks(self):
        self.task['base_commit'] = 'f' * 40
        self.assert_denied(self.task, 'base_commit_changed')

    def test_new_file_succeeds_only_when_absent(self):
        task = self.make_task(path='src/new.py', expected=None)
        r = self.controller.write(task, dry_run=False)
        self.assertTrue(r.applied)
        self.assertEqual((self.root / 'src/new.py').read_text(), 'print(2)\n')

    def test_new_file_with_existing_content_blocks(self):
        task = self.make_task(path='src/new.py', expected=None)
        (self.root / 'src/new.py').write_text('existing\n')
        self.assert_denied(task, 'unexpected_existing_contents')

    def test_unsupported_untrusted_scope(self):
        task = self.make_task(path='src/other.py', expected=None)
        task['trusted_scope'] = ['src/other.py']
        self.assert_denied(task, 'write_outside_trusted_scope')

    def test_sensitive_payload_blocks(self):
        task = self.make_task(content='change Stripe checkout\n')
        self.assert_denied(task, 'sensitive_payload_requires_external_approval')

    def test_sensitive_objective_blocks(self):
        task = self.make_task()
        task['objective'] = 'Change Stripe checkout'
        self.assert_denied(task, 'sensitive_intent_requires_external_approval')

    def test_extra_fields_rejected(self):
        self.task['operations'][0]['approved'] = True
        self.assert_denied(self.task, 'unexpected_write_fields')

    def test_multiple_writes_rejected(self):
        self.task['operations'].append({'type':'write_file', 'path':'src/new.py',
                                        'content':'x', 'expected_sha256':None})
        self.assert_denied(self.task, 'single_write_only')
        self.assertFalse((self.root / 'src/new.py').exists())

    def test_symlink_target_rejected(self):
        (self.root / 'src/escape.py').symlink_to(self.root / 'src/safe.py')
        self.assert_denied(self.make_task(path='src/escape.py', expected=None), 'symlink_not_allowed')

    def test_symlink_parent_rejected(self):
        (self.root / 'src2').symlink_to(self.root / 'src', target_is_directory=True)
        with self.assertRaises(OperationDenied) as ctx:
            ScopedController(self.root, frozenset({'src2/new.py'}))
        self.assertIn('invalid_trusted_scope', ctx.exception.reasons)

    def test_directory_target_rejected(self):
        (self.root / 'src/new.py').mkdir()
        self.assert_denied(self.make_task(path='src/new.py', expected=None), 'not_regular_file')

    def test_too_large_write_blocks(self):
        self.assert_denied(self.make_task(content='a' * 131073), 'write_too_large')

    def test_missing_parent_cannot_be_created(self):
        ctl = ScopedController(self.root, frozenset({'not_created/new.py'}))
        with self.assertRaises(OperationDenied):
            ctl.write(self.make_task(path='not_created/new.py', expected=None), dry_run=False)
        self.assertFalse((self.root / 'not_created').exists())

    def test_protected_harness_code_never_in_scope(self):
        task = self.make_task(path='frontier/runtime/gate.py', expected=None)
        ctl = ScopedController(self.root, frozenset({'frontier/runtime/gate.py'}))
        with self.assertRaises(OperationDenied) as ctx:
            ctl.write(task, dry_run=False)
        self.assertIn('protected_surface', ctx.exception.reasons)

    def test_hidden_holdout_cannot_be_read(self):
        decision = evaluate_task({'task_id':'a', 'objective':'inspect', 'base_commit':self.commit,
                                  'risk':'low', 'operations':[
                                      {'type':'read_file', 'path':'frontier/evals/holdout/secret.json'}]},
                                 repo_root=self.root, trusted_scope=frozenset())
        self.assertFalse(decision.allowed)
        self.assertIn('protected_read_surface', decision.reasons)

    def test_no_git_repository_fails_closed(self):
        root = Path(self.d.name) / 'separate'
        root.mkdir()
        (root/'src').mkdir()
        ctl = ScopedController(root, frozenset({'src/new.py'}))
        with self.assertRaises(OperationDenied) as ctx:
            ctl.write(self.make_task(path='src/new.py', expected=None), dry_run=False)
        self.assertIn('pinned_commit_unavailable', ctx.exception.reasons)


if __name__ == '__main__':
    unittest.main()
