"""Trusted-host test executor for a narrow, fixed unittest command profile.

NOT A SECURITY SANDBOX: runnable test code can execute arbitrary Python. The host
must run this module outside the agent's privileges, using independently owned
and pinned test suites in an OS-isolated environment. The agent must never
control executable argv, the signing key, or the evidence root.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Iterable

from .controller import OperationDenied, _head_commit
from .evidence_v2 import issue_receipt
from .gate import validate_repo_path


@dataclass(frozen=True)
class TestProfile:
    command_id: str
    argv: tuple[str, ...]
    timeout_seconds: int = 30


def unittest_profile(suite_directory: str = 'frontier/tests') -> TestProfile:
    """Host should provide a frozen, independently owned test directory."""
    return TestProfile('unittest', (sys.executable, '-m', 'unittest', 'discover', '-s', suite_directory, '-q'))


def scope_digest(root: Path, paths: Iterable[str]) -> str:
    """Digest exact approved paths; never read symlinks or files outside root."""
    names = sorted(set(paths))
    if not names:
        raise OperationDenied(('empty_digest_scope',))
    entries = []
    for name in names:
        normalized, err = validate_repo_path(name, root)
        if err or normalized is None:
            raise OperationDenied(('invalid_digest_scope',))
        path = Path(root) / normalized
        if not path.is_file():
            raise OperationDenied(('missing_digest_file',))
        if path.stat().st_size > 5 * 1024 * 1024:
            raise OperationDenied(('digest_file_too_large',))
        entries.append({'path': normalized, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    blob = json.dumps(entries, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(blob).hexdigest()


class TrustedTestExecutor:
    """Called by trusted host only; do not expose this object to agent code."""

    def __init__(self, workspace: Path, evidence_root: Path, *, signer_key: bytes,
                 issuer: str, profiles: tuple[TestProfile, ...]):
        self.workspace = Path(workspace).resolve(strict=True)
        self.evidence_root = Path(evidence_root).resolve(strict=True)
        if self.workspace == self.evidence_root or self.evidence_root.is_relative_to(self.workspace):
            raise OperationDenied(('evidence_must_be_outside_workspace',))
        self.signer_key = signer_key
        self.issuer = issuer
        self.profiles = {p.command_id: p for p in profiles}
        if len(self.profiles) != len(profiles):
            raise OperationDenied(('duplicate_profile_id',))

    def run(self, *, profile_id: str, task_id: str, base_commit: str,
            run_id: str, scoped_paths: frozenset[str]) -> dict:
        if profile_id not in self.profiles:
            raise OperationDenied(('unknown_test_profile',))
        profile = self.profiles[profile_id]
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', run_id):
            raise OperationDenied(('invalid_run_id',))
        if not (1 <= profile.timeout_seconds <= 120):
            raise OperationDenied(('unbounded_test_timeout',))
        if base_commit != _head_commit(self.workspace):
            raise OperationDenied(('base_commit_changed',))
        before_digest = scope_digest(self.workspace, scoped_paths)
        started = time.monotonic()
        env = {
            'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
            'HOME': '/nonexistent',
            'PYTHONNOUSERSITE': '1',
            'PYTHONDONTWRITEBYTECODE': '1',
        }
        try:
            run = subprocess.run(profile.argv, cwd=self.workspace, timeout=profile.timeout_seconds,
                                 capture_output=True, text=True, errors='replace',
                                 check=False, env=env)
            code, output = run.returncode, run.stdout[-8192:] + '\n' + run.stderr[-8192:]
        except subprocess.TimeoutExpired:
            code, output = 124, 'test timeout'
        duration_ms = round((time.monotonic() - started) * 1000)
        try:
            after_digest = scope_digest(self.workspace, scoped_paths)
            stable = before_digest == after_digest
        except OperationDenied:
            stable = False
        found = re.findall(r'Ran\s+(\d+)\s+tests?\s+in\s+', output)
        count = int(found[-1]) if found else 0
        if not stable:
            code, count = 125, 0
            output += '\nSCOPE CONTENT CHANGED WHILE VERIFYING'
        artifact_name = f'{run_id}.json'
        artifact_path = self.evidence_root / artifact_name
        artifact_content = json.dumps({
            'task_id': task_id, 'base_commit': base_commit,
            'workspace_digest': before_digest, 'command_id': profile.command_id,
            'exit_code': code, 'tests_run': count, 'duration_ms': duration_ms,
            'log_excerpt': output,
        }, sort_keys=True).encode('utf-8')
        try:
            fd = os.open(artifact_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as file:
                file.write(artifact_content)
                file.flush()
                os.fsync(file.fileno())
        except FileExistsError as exc:
            raise OperationDenied(('duplicate_run_id',)) from exc
        # The receipt is only a passing verification when the independent tests
        # passed and the verified scope remained unchanged during execution.
        return issue_receipt(
            key=self.signer_key, issuer=self.issuer, task_id=task_id,
            base_commit=base_commit, workspace_digest=before_digest,
            run_id=run_id, artifact=artifact_name,
            sha256=hashlib.sha256(artifact_content).hexdigest(),
            exit_code=code, tests_run=count, command_id=profile.command_id,
        )
