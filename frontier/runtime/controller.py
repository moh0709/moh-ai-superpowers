"""Narrow, auditable file-mutation adapter for a trusted host controller.

This is NOT a general process sandbox. Agent runtimes must expose this adapter as
an exclusive mutation tool and deny direct shell/filesystem/GitHub write access.
Only one write is supported per operation batch in this initial implementation,
so a failed write cannot leave a half-applied multi-file transaction.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import subprocess
import uuid
from typing import Any, Mapping

from .gate import Decision, _sensitive, evaluate_task, validate_repo_path

MAX_WRITE_BYTES = 128 * 1024
SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")
COMMIT_HEX = re.compile(r"[0-9a-f]{40}\Z")


@dataclass(frozen=True)
class WriteReceipt:
    path: str
    before_sha256: str | None
    after_sha256: str
    base_commit: str
    applied: bool
    verification_status: str = "Not verified"


class OperationDenied(Exception):
    def __init__(self, reasons: tuple[str, ...]):
        self.reasons = reasons
        super().__init__(", ".join(reasons))


def _file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _open_parent(root: Path, relative_path: str) -> tuple[int, str]:
    """Anchor parent walks to a directory descriptor; forbid symlink components.

    Linux/Unix descriptor operations are used deliberately. This check does not
    isolate the host from an untrusted process sharing the same credentials.
    """
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise OperationDenied(("unsupported_host_for_descriptor_writes",))
    bits = relative_path.split("/")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(root, flags)
    try:
        for part in bits[:-1]:
            new_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = new_fd
        return fd, bits[-1]
    except BaseException:
        os.close(fd)
        raise


def _read_existing(parent_fd: int, basename: str) -> bytes | None:
    try:
        fd = os.open(basename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
    except FileNotFoundError:
        return None
    try:
        import stat
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise OperationDenied(("not_regular_file",))
        if st.st_size > MAX_WRITE_BYTES:
            raise OperationDenied(("existing_file_too_large",))
        with os.fdopen(fd, "rb", closefd=False) as file:
            content = file.read(MAX_WRITE_BYTES + 1)
        if len(content) > MAX_WRITE_BYTES:
            raise OperationDenied(("existing_file_too_large",))
        return content
    finally:
        os.close(fd)


def _head_commit(root: Path) -> str:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": "/nonexistent",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_OPTIONAL_LOCKS": "0",
    }
    try:
        top = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            text=True, capture_output=True, timeout=5, check=False, env=env,
        )
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD^{commit}"],
            text=True, capture_output=True, timeout=5, check=False, env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OperationDenied(("pinned_commit_unavailable",)) from exc
    commit = proc.stdout.strip()
    if (top.returncode or Path(top.stdout.strip()).resolve() != root or
            proc.returncode or not COMMIT_HEX.fullmatch(commit)):
        raise OperationDenied(("pinned_commit_unavailable",))
    return commit


class ScopedController:
    """Host-owned adapter; task input must NOT supply ``trusted_scope``."""

    def __init__(self, repo_root: Path, trusted_scope: frozenset[str]):
        root = Path(repo_root)
        if root.is_symlink() or not root.is_dir():
            raise OperationDenied(("invalid_workspace",))
        self.root = root.resolve(strict=True)
        self.trusted_scope = frozenset(trusted_scope)
        for p in self.trusted_scope:
            path, err = validate_repo_path(p, self.root)
            if err or path != p:
                raise OperationDenied(("invalid_trusted_scope",))

    def write(self, task: Mapping[str, Any], *, dry_run: bool = True) -> WriteReceipt:
        """Perform at most one explicitly scoped, pinned and hash-checked write.

        This function does not run arbitrary commands, tests, or deployment.
        Its receipt is intentionally **not** verification evidence.
        """
        decision: Decision = evaluate_task(task, repo_root=self.root, trusted_scope=self.trusted_scope)
        if not decision.allowed:
            raise OperationDenied(decision.reasons)
        if task.get("risk") != "low":
            raise OperationDenied(("low_risk_only",))
        if not isinstance(task.get("operations"), list):
            raise OperationDenied(("missing_operations",))
        writes = [op for op in task["operations"] if op.get("type") == "write_file"]
        if len(writes) != 1 or len(task["operations"]) != 1:
            raise OperationDenied(("single_write_only",))
        op = writes[0]
        if set(op) != {"type", "path", "content", "expected_sha256"}:
            raise OperationDenied(("unexpected_write_fields",))
        content = op["content"]
        if not isinstance(content, str):
            raise OperationDenied(("invalid_content",))
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_WRITE_BYTES:
            raise OperationDenied(("write_too_large",))
        if _sensitive(content):
            raise OperationDenied(("sensitive_payload_requires_external_approval",))
        expected = op["expected_sha256"]
        if expected is not None and (not isinstance(expected, str) or not SHA256_HEX.fullmatch(expected)):
            raise OperationDenied(("invalid_expected_hash",))
        if task["base_commit"] != _head_commit(self.root):
            raise OperationDenied(("base_commit_changed",))
        rel = op["path"]
        _canonical, err = validate_repo_path(rel, self.root)
        if err:
            raise OperationDenied((err,))
        try:
            parent_fd, name = _open_parent(self.root, rel)
        except OSError as exc:
            raise OperationDenied(("unsafe_parent_directory",)) from exc
        try:
            before = _read_existing(parent_fd, name)
            current_hash = None if before is None else _file_hash(before)
            if current_hash != expected:
                raise OperationDenied(("unexpected_existing_contents",))
            after_hash = _file_hash(encoded)
            if not dry_run:
                temp = f".moh-{uuid.uuid4().hex}.tmp"
                fd = None
                try:
                    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=parent_fd)
                    with os.fdopen(fd, "wb") as out:
                        fd = None
                        out.write(encoded)
                        out.flush()
                        os.fsync(out.fileno())
                    # Revalidate target immediately prior to replacing it.
                    # Compare-and-swap by digest, not an agent-reported 'approved' field.
                    latest = _read_existing(parent_fd, name)
                    if (None if latest is None else _file_hash(latest)) != expected:
                        raise OperationDenied(("concurrent_edit_detected",))
                    os.replace(temp, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                    temp = ""
                    os.fsync(parent_fd)
                finally:
                    if fd is not None:
                        os.close(fd)
                    if temp:
                        try:
                            os.unlink(temp, dir_fd=parent_fd)
                        except FileNotFoundError:
                            pass
            return WriteReceipt(rel, current_hash, after_hash, task["base_commit"], not dry_run)
        except OSError as exc:
            raise OperationDenied(("filesystem_error",)) from exc
        finally:
            os.close(parent_fd)
