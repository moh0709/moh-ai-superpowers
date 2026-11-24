"""MOH Frontier P0: fail-closed, non-executing task/evidence gate.

Security boundary: trusted_scope is supplied by the controller, not by an agent.
This module does not sandbox an agent or intercept arbitrary shell/tool access.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
import hashlib
import hmac
import json
import re

SAFE_ACTIONS = frozenset({'read_file', 'write_file', 'report'})
PROTECTED_PATHS = (
    'frontier/policies/', 'frontier/benchmarks/hidden/',
    'frontier/runtime/gate.py', 'frontier/runtime/score.py',
    '.github/workflows/', 'docs/DUE_DILIGENCE.md', 'docs/GOVERNANCE.md',
)
SENSITIVE_TOKENS = frozenset({
    'auth', 'authentication', 'authorization', 'payment', 'payments',
    'stripe', 'migration', 'migrations', 'secret', 'secrets', 'credential',
    'credentials', 'deploy', 'deployment', 'production', 'prod', 'rls',
})

@dataclass(frozen=True)
class Decision:
    allowed: bool
    reasons: tuple[str, ...]


def validate_repo_path(value: Any, repo_root: Path) -> tuple[str | None, str | None]:
    """Canonicalize a repo-relative path; reject escaping paths and symlinks."""
    if not isinstance(value, str) or not value or len(value) > 4096:
        return None, 'invalid_path'
    if any(c in value for c in ('\\', '\x00', '%')) or ':' in value or value.startswith('/'):
        return None, 'invalid_path'
    components = value.split('/')
    if any(c in ('', '.', '..') for c in components):
        return None, 'traversal_or_ambiguous_path'
    try:
        root = repo_root.resolve(strict=True)
        proposed = root.joinpath(*components)
        # Block symlink escapes and symlink components even when target stays inside root.
        cursor = root
        for part in components:
            cursor = cursor / part
            if cursor.is_symlink():
                return None, 'symlink_not_allowed'
        resolved = proposed.resolve(strict=False)
        if not resolved.is_relative_to(root):
            return None, 'outside_workspace'
    except (OSError, RuntimeError, ValueError):
        return None, 'invalid_workspace'
    return value, None


def _sensitive(path: str) -> bool:
    if path.startswith('.env') or '/.env' in path or '/.git/' in ('/'+path+'/'):
        return True
    pieces = re.split(r'[^a-z0-9]+', path.casefold())
    return any(part in SENSITIVE_TOKENS for part in pieces)


def evaluate_task(task: Mapping[str, Any], *, repo_root: Path,
                  trusted_scope: frozenset[str]) -> Decision:
    """Only evaluates a structured request; never dispatches operations."""
    reasons: list[str] = []
    if not isinstance(task, Mapping):
        return Decision(False, ('invalid_contract',))
    if not isinstance(task.get('task_id'), str) or not task['task_id'].strip():
        reasons.append('missing_task_id')
    if not isinstance(task.get('objective'), str) or not task['objective'].strip():
        reasons.append('missing_objective')
    if not isinstance(task.get('base_commit'), str) or not re.fullmatch(r'[a-f0-9]{40}', task['base_commit']):
        reasons.append('missing_pinned_commit')
    if task.get('risk') not in {'low', 'medium', 'high'}:
        reasons.append('invalid_risk')
    if task.get('risk') in {'medium', 'high'} and not task.get('rollback_plan'):
        reasons.append('missing_rollback')
    if task.get('risk') == 'high':
        reasons.append('external_approval_required')

    operations = task.get('operations')
    # Fail closed on obvious sensitive intents even when the chosen filename is benign.
    # This is a supplementary heuristic, NOT a substitute for checking actual diffs.
    if isinstance(operations, list) and any(isinstance(op, Mapping) and op.get('type') == 'write_file' for op in operations):
        if _sensitive(str(task.get('objective', ''))):
            reasons.append('sensitive_intent_requires_external_approval')
    if not isinstance(operations, list) or not operations:
        reasons.append('missing_operations')
        operations = []
    for op in operations:
        if not isinstance(op, Mapping):
            reasons.append('invalid_operation')
            continue
        kind = op.get('type')
        if kind not in SAFE_ACTIONS:
            reasons.append('unsupported_action')
            continue
        if kind == 'report':
            continue
        path, err = validate_repo_path(op.get('path'), repo_root)
        if err:
            reasons.append(err)
            continue
        assert path is not None
        if _sensitive(path):
            reasons.append('sensitive_file_requires_external_approval')
        if kind == 'write_file':
            if path not in trusted_scope:
                reasons.append('write_outside_trusted_scope')
            if any(path == p or path.startswith(p) for p in PROTECTED_PATHS):
                reasons.append('protected_surface')
            if task.get('risk') == 'medium':
                reasons.append('medium_risk_requires_external_approval')
    # A boolean "approved" from the agent's request is intentionally ignored.
    return Decision(not reasons, tuple(sorted(set(reasons))))


SIGNED_EVIDENCE_FIELDS = ('task_id', 'base_commit', 'artifact', 'sha256', 'exit_code', 'tests_run')


def sign_verification(evidence: Mapping[str, Any], controller_key: bytes) -> str:
    """Controller-only helper. The signing key must never be passed to an agent."""
    if not controller_key or any(k not in evidence for k in SIGNED_EVIDENCE_FIELDS):
        raise ValueError('missing signing key or required evidence field')
    payload = {k: evidence[k] for k in SIGNED_EVIDENCE_FIELDS}
    message = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hmac.new(controller_key, message, hashlib.sha256).hexdigest()


def verify_completion(claim: str, trusted_evidence: Mapping[str, Any] | None,
                      *, evidence_root: Path, verification_key: bytes | None = None,
                      expected_task_id: str | None = None,
                      expected_base_commit: str | None = None) -> Decision:
    """Reconcile completion claim with externally signed, task-bound evidence."""
    if claim not in {'Verified', 'Partially verified', 'Not verified', 'Blocked'}:
        return Decision(False, ('invalid_claim',))
    if claim != 'Verified':
        return Decision(True, ())
    if not isinstance(trusted_evidence, Mapping):
        return Decision(False, ('missing_independent_evidence',))
    if not verification_key or not expected_task_id or not expected_base_commit:
        return Decision(False, ('missing_controller_trust_anchor',))
    if trusted_evidence.get('task_id') != expected_task_id or trusted_evidence.get('base_commit') != expected_base_commit:
        return Decision(False, ('evidence_task_binding_mismatch',))
    try:
        correct_signature = sign_verification(trusted_evidence, verification_key)
    except (ValueError, TypeError, OverflowError):
        return Decision(False, ('invalid_evidence_payload',))
    if not isinstance(trusted_evidence.get('signature'), str) or not hmac.compare_digest(trusted_evidence['signature'], correct_signature):
        return Decision(False, ('invalid_verifier_signature',))
    if trusted_evidence.get('exit_code') != 0 or not isinstance(trusted_evidence.get('tests_run'), int) or trusted_evidence['tests_run'] < 1:
        return Decision(False, ('verification_not_passing',))
    artifact, err = validate_repo_path(trusted_evidence.get('artifact'), evidence_root)
    if err:
        return Decision(False, ('invalid_evidence_path',))
    assert artifact is not None
    path = evidence_root / artifact
    if not path.is_file():
        return Decision(False, ('missing_artifact',))
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if trusted_evidence.get('sha256') != actual:
        return Decision(False, ('evidence_hash_mismatch',))
    return Decision(True, ())
