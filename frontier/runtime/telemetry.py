"""Minimal append-only local audit metadata, outside the agent workspace.

No prompts, file bodies, source code or raw tool arguments are logged. This is
an operational log, not a tamper-proof audit service or authenticated model
usage ledger. Collect model token usage from a trusted host billing stream.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import time
import uuid


class AuditLog:
    def __init__(self, path: Path, workspace: Path):
        path = Path(path).absolute()
        root = Path(workspace).resolve(strict=True)
        try:
            parent = path.parent.resolve(strict=True)
        except OSError as exc:
            raise ValueError('audit parent unavailable') from exc
        if (path.is_relative_to(root) or parent.is_relative_to(root) or
                not parent.is_dir() or path.is_symlink()):
            raise ValueError('audit file must be outside the workspace')
        self.path = path
        self.root = root

    def append(self, *, task_id: str, tool: str, status: str, reason: str, duration_ms: float) -> None:
        item = {
            'schema':'moh-frontier-tool-trace-v1', 'event_id':uuid.uuid4().hex,
            'unix_ms': int(time.time()*1000), 'task_id':task_id,
            'tool':tool, 'status':status, 'reason':reason,
            'duration_ms':round(duration_ms,3),
            'tokens_in':None, 'tokens_out':None, 'cost_usd':None,
        }
        blob = (json.dumps(item, sort_keys=True, separators=(',', ':'))+'\n').encode()
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
        if hasattr(os, 'O_NOFOLLOW'):
            flags |= os.O_NOFOLLOW
        fd = os.open(self.path, flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError('unsafe audit target')
            os.write(fd, blob)
            os.fsync(fd)
        finally:
            os.close(fd)
