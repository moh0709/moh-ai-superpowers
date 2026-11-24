"""Short-lived, replay-resistant test receipts for a separately privileged verifier.

The signer and replay database MUST be controlled by the host, outside the agent's
filesystem and process. HMAC authenticates who signed metadata; it does not prove
that a test really ran unless that trusted verifier measures the test itself.
"""
from __future__ import annotations

import hashlib
from contextlib import closing
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time
from typing import Any, Mapping

from .gate import Decision, validate_repo_path

VERSION = 2
LIFETIME_SECONDS = 600
EXPECTED_FIELDS = frozenset({
    "version", "issuer", "task_id", "base_commit", "workspace_digest",
    "run_id", "nonce", "issued_at", "expires_at", "artifact", "sha256",
    "exit_code", "tests_run", "command_id",
})
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
NONCE = re.compile(r"[0-9a-f]{32}\Z")
LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


def _bytes_to_sign(data: Mapping[str, Any]) -> bytes:
    if set(data) != EXPECTED_FIELDS:
        raise ValueError("unknown_or_missing_evidence_fields")
    return json.dumps(dict(data), sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def issue_receipt(*, key: bytes, issuer: str, task_id: str, base_commit: str,
                  workspace_digest: str, run_id: str, artifact: str, sha256: str,
                  exit_code: int, tests_run: int, command_id: str,
                  now: int | None = None, lifetime_seconds: int = 300) -> dict[str, Any]:
    """Issuer MUST have obtained exit_code/tests_run from its own execution."""
    current = int(time.time()) if now is None else now
    receipt: dict[str, Any] = dict(
        version=VERSION, issuer=issuer, task_id=task_id,
        base_commit=base_commit, workspace_digest=workspace_digest,
        run_id=run_id, nonce=secrets.token_hex(16), issued_at=current,
        expires_at=current + lifetime_seconds, artifact=artifact,
        sha256=sha256, exit_code=exit_code, tests_run=tests_run,
        command_id=command_id,
    )
    _validate_fields(receipt)
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("key_must_be_at_least_32_bytes")
    receipt["signature"] = hmac.new(key, _bytes_to_sign(receipt), hashlib.sha256).hexdigest()
    return receipt


def _validate_fields(receipt: Mapping[str, Any]) -> None:
    if receipt.get("version") != VERSION or type(receipt.get("version")) is not int:
        raise ValueError("invalid_version")
    for field in ("issuer", "task_id", "run_id", "command_id"):
        if not isinstance(receipt.get(field), str) or not LABEL.fullmatch(receipt[field]):
            raise ValueError("invalid_" + field)
    for field, pattern in (("base_commit", HEX40), ("workspace_digest", HEX64),
                           ("sha256", HEX64), ("nonce", NONCE)):
        if not isinstance(receipt.get(field), str) or not pattern.fullmatch(receipt[field]):
            raise ValueError("invalid_" + field)
    if not isinstance(receipt.get("artifact"), str) or not receipt["artifact"]:
        raise ValueError("invalid_artifact")
    for field in ("issued_at", "expires_at", "exit_code", "tests_run"):
        if type(receipt.get(field)) is not int:
            raise ValueError("invalid_" + field)
    if not 0 < receipt["expires_at"] - receipt["issued_at"] <= LIFETIME_SECONDS:
        raise ValueError("invalid_expiry_window")


class ReplayStore:
    """Host-owned durable nonce ledger; use a path outside agent-writeable roots."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS used_receipts (nonce TEXT PRIMARY KEY, run_id TEXT UNIQUE NOT NULL, verified_at INTEGER NOT NULL)")

    def register_once(self, nonce: str, run_id: str, verified_at: int) -> bool:
        try:
            with closing(sqlite3.connect(self.path, timeout=3)) as db, db:
                db.execute("INSERT INTO used_receipts(nonce, run_id, verified_at) VALUES (?, ?, ?)",
                           (nonce, run_id, verified_at))
            return True
        except sqlite3.IntegrityError:
            return False


def verify_receipt(receipt: Mapping[str, Any], *, key: bytes, issuer: str,
                   task_id: str, base_commit: str, workspace_digest: str,
                   evidence_root: Path, replay_store: ReplayStore,
                   now: int | None = None) -> Decision:
    """Consume a receipt exactly once; claim success only after this returns allowed."""
    if not isinstance(receipt, Mapping):
        return Decision(False, ("missing_receipt",))
    try:
        content = {k: v for k, v in receipt.items() if k != "signature"}
        _validate_fields(content)
        serialized = _bytes_to_sign(content)
        if not isinstance(key, bytes) or len(key) < 32:
            return Decision(False, ("missing_trust_key",))
        sig = receipt.get("signature")
        if not isinstance(sig, str) or not HEX64.fullmatch(sig):
            return Decision(False, ("invalid_signature",))
        correct_sig = hmac.new(key, serialized, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, correct_sig):
            return Decision(False, ("invalid_signature",))
    except (ValueError, TypeError, OverflowError):
        return Decision(False, ("invalid_receipt",))
    if any((content["issuer"] != issuer, content["task_id"] != task_id,
            content["base_commit"] != base_commit,
            content["workspace_digest"] != workspace_digest)):
        return Decision(False, ("binding_mismatch",))
    current = int(time.time()) if now is None else now
    if type(current) is not int or content["issued_at"] > current + 30 or current >= content["expires_at"]:
        return Decision(False, ("expired_or_future_receipt",))
    if content["exit_code"] != 0 or content["tests_run"] < 1:
        return Decision(False, ("tests_not_passing",))
    artifact, err = validate_repo_path(content["artifact"], evidence_root)
    if err:
        return Decision(False, ("invalid_artifact_path",))
    assert artifact is not None
    try:
        artifact_file = Path(evidence_root) / artifact
        if artifact_file.stat().st_size > 1024 * 1024:
            return Decision(False, ("artifact_too_large",))
        payload = artifact_file.read_bytes()
        if len(payload) > 1024 * 1024:
            return Decision(False, ("artifact_too_large",))
    except OSError:
        return Decision(False, ("artifact_unavailable",))
    if hashlib.sha256(payload).hexdigest() != content["sha256"]:
        return Decision(False, ("artifact_digest_mismatch",))
    try:
        inserted = replay_store.register_once(content["nonce"], content["run_id"], current)
    except sqlite3.Error:
        return Decision(False, ("replay_store_unavailable",))
    if not inserted:
        return Decision(False, ("replayed_receipt",))
    return Decision(True, ())
