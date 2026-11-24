"""Model Context Protocol stdio tool gateway for trusted host-owned coding tasks.

Exposes only read_file, preview_write, and apply_write. A real coding agent can
connect as an MCP client; it must NOT also have shell/filesystem/GitHub write
access. This module itself is not an OS sandbox and does not secure other tools.

The tool caller cannot set task identity, objective, risk, Git pin, allowlisted
paths, or permitted branch. Those belong exclusively to the host configuration.
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
from typing import Any, Mapping, TextIO

from .controller import OperationDenied, ScopedController, _head_commit, _open_parent, _read_existing
from .gate import _sensitive, evaluate_task, validate_repo_path
from .telemetry import AuditLog

MAX_LINE_BYTES = 512 * 1024
MAX_CALLS = 100


@dataclass(frozen=True)
class HostTask:
    task_id: str
    objective: str
    workspace: Path
    branch: str
    base_commit: str
    read_scope: frozenset[str]
    write_scope: frozenset[str]
    max_calls: int = MAX_CALLS

    def validate(self) -> None:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', self.task_id):
            raise OperationDenied(('invalid_host_task_id',))
        if not isinstance(self.objective, str) or not self.objective.strip():
            raise OperationDenied(('invalid_host_objective',))
        if not isinstance(self.branch, str) or not self.branch or self.branch in ('main', 'master'):
            raise OperationDenied(('protected_branch_not_allowed',))
        if not isinstance(self.max_calls, int) or isinstance(self.max_calls, bool) or not 1 <= self.max_calls <= 1000:
            raise OperationDenied(('invalid_call_budget',))
        if not self.write_scope or not self.read_scope.issuperset(self.write_scope):
            raise OperationDenied(('invalid_host_scope',))
        if self.base_commit != _head_commit(self.workspace):
            raise OperationDenied(('base_commit_changed',))
        for path in self.read_scope | self.write_scope:
            canonical, error = validate_repo_path(path, self.workspace)
            if error or canonical != path or _sensitive(path):
                raise OperationDenied(('invalid_host_scope',))
        if not _branch_matches(self.workspace, self.branch):
            raise OperationDenied(('wrong_branch',))
        # Protected implementation, evaluator, and hidden tests cannot enter the write scope.
        trial = {
            'task_id': self.task_id, 'objective': self.objective,
            'base_commit': self.base_commit, 'risk': 'low',
            'operations': [{'type': 'write_file', 'path': p} for p in sorted(self.write_scope)],
        }
        decision = evaluate_task(trial, repo_root=self.workspace, trusted_scope=self.write_scope)
        if not decision.allowed:
            raise OperationDenied(decision.reasons)


def _branch_matches(root: Path, expected: str) -> bool:
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': '/nonexistent',
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_OPTIONAL_LOCKS': '0'}
    try:
        result = subprocess.run(['git', '-C', str(root), 'symbolic-ref', '--quiet', '--short', 'HEAD'],
                                capture_output=True, text=True, timeout=5, env=env, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() == expected


TOOLS = [
    {'name':'frontier.read_file','description':'Read an explicitly allowed source file with SHA-256. Never reads hidden tests or private files.',
     'inputSchema':{'type':'object','properties':{'path':{'type':'string'}},'required':['path'],'additionalProperties':False}},
    {'name':'frontier.preview_write','description':'Validate proposed scoped write without changing source. Requires expected_sha256 (null only for new files).',
     'inputSchema':{'type':'object','properties':{'path':{'type':'string'},'content':{'type':'string'},'expected_sha256':{'type':['string','null']}},
                    'required':['path','content','expected_sha256'],'additionalProperties':False}},
    {'name':'frontier.apply_write','description':'Apply one low-risk, pinned, hash-checked scoped write. Does not verify completion.',
     'inputSchema':{'type':'object','properties':{'path':{'type':'string'},'content':{'type':'string'},'expected_sha256':{'type':['string','null']}},
                    'required':['path','content','expected_sha256'],'additionalProperties':False}},
]


class Gateway:
    """Trusted host object; only handle() should be reached by the untrusted MCP client."""

    def __init__(self, task: HostTask, audit: AuditLog):
        task.validate()
        self.task = task
        self.controller = ScopedController(task.workspace, task.write_scope)
        self.audit = audit
        self.calls = 0
        self.legacy_initialized = False
        self.legacy_ready = False

    def _read(self, args: Mapping[str, Any]) -> dict:
        if set(args) != {'path'} or not isinstance(args['path'], str):
            raise OperationDenied(('invalid_read_arguments',))
        name = args['path']
        if name not in self.task.read_scope:
            raise OperationDenied(('read_outside_scope',))
        decision = evaluate_task({
            'task_id': self.task.task_id, 'objective': self.task.objective,
            'base_commit': self.task.base_commit, 'risk': 'low',
            'operations': [{'type': 'read_file', 'path': name}],
        }, repo_root=self.task.workspace, trusted_scope=self.task.write_scope)
        if not decision.allowed:
            raise OperationDenied(decision.reasons)
        if not _branch_matches(self.task.workspace, self.task.branch) or _head_commit(self.task.workspace) != self.task.base_commit:
            raise OperationDenied(('repository_pin_changed',))
        try:
            parent_fd, basename = _open_parent(self.task.workspace, name)
            try:
                content = _read_existing(parent_fd, basename)
            finally:
                os.close(parent_fd)
        except (OSError, UnicodeError) as exc:
            raise OperationDenied(('read_failed',)) from exc
        if content is None:
            raise OperationDenied(('missing_file',))
        try:
            text = content.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise OperationDenied(('binary_file_not_supported',)) from exc
        return {'path': name, 'content': text, 'sha256': hashlib.sha256(content).hexdigest(),
                'verification_status': 'Not verified'}

    def _write(self, args: Mapping[str, Any], *, dry_run: bool) -> dict:
        if set(args) != {'path', 'content', 'expected_sha256'}:
            raise OperationDenied(('invalid_write_arguments',))
        path = args['path']
        if not isinstance(path, str) or path not in self.task.write_scope:
            raise OperationDenied(('write_outside_scope',))
        if not _branch_matches(self.task.workspace, self.task.branch):
            raise OperationDenied(('wrong_branch',))
        request = {
            'task_id': self.task.task_id, 'objective': self.task.objective,
            'base_commit': self.task.base_commit, 'risk': 'low',
            'operations': [{'type': 'write_file', 'path': path,
                            'content': args['content'], 'expected_sha256': args['expected_sha256']}],
        }
        receipt = self.controller.write(request, dry_run=dry_run)
        return {'path': receipt.path, 'before_sha256': receipt.before_sha256,
                'after_sha256': receipt.after_sha256, 'applied': receipt.applied,
                'verification_status': receipt.verification_status}

    def call(self, name: str, args: Mapping[str, Any]) -> dict:
        start = time.monotonic_ns()
        self.calls += 1
        status = 'denied'
        reason = ''
        try:
            if self.calls > self.task.max_calls:
                raise OperationDenied(('call_budget_exceeded',))
            if not isinstance(args, Mapping):
                raise OperationDenied(('invalid_arguments',))
            if name == 'frontier.read_file':
                data = self._read(args)
            elif name == 'frontier.preview_write':
                data = self._write(args, dry_run=True)
            elif name == 'frontier.apply_write':
                data = self._write(args, dry_run=False)
            else:
                raise OperationDenied(('unknown_tool',))
            status = 'ok'
            return {'content': [{'type': 'text', 'text': json.dumps(data, sort_keys=True)}]}
        except (OperationDenied, TypeError, UnicodeError, ValueError) as exc:
            reason = ','.join(exc.reasons) if isinstance(exc, OperationDenied) else 'invalid_input'
            return {'content': [{'type': 'text', 'text': json.dumps({'denied': reason})}], 'isError': True}
        finally:
            self.audit.append(task_id=self.task.task_id, tool=name if isinstance(name,str) else 'invalid',
                              status=status, reason=reason, duration_ms=(time.monotonic_ns()-start)/1e6)

    def dispatch(self, request: Any) -> dict | None:
        """Support legacy MCP 2025-03-26 and modern MCP 2026-07-28.

        Modern calls require per-request metadata, never implicit negotiation.
        Older clients need initialize + notifications/initialized before tools.
        """
        if not isinstance(request, dict) or request.get('jsonrpc') != '2.0':
            return {'jsonrpc':'2.0','id':request.get('id') if isinstance(request,dict) else None,
                    'error':{'code':-32600,'message':'Invalid Request'}}
        method = request.get('method')
        if 'id' not in request:
            if method == 'notifications/initialized' and self.legacy_initialized:
                self.legacy_ready = True
            # Notifications never run tools or produce a response.
            return None
        req_id = request['id']
        if not (isinstance(req_id, (str,int)) and not isinstance(req_id,bool)) and req_id is not None:
            return {'jsonrpc':'2.0','id':None,'error':{'code':-32600,'message':'Invalid Request'}}

        def fail(code: int, msg: str, data: dict | None = None) -> dict:
            err = {'code':code, 'message':msg}
            if data is not None:
                err['data'] = data
            return {'jsonrpc':'2.0','id':req_id,'error':err}

        def answer(result: dict, *, modern: bool) -> dict:
            if modern:
                result = dict(result)
                result['resultType'] = 'complete'
                result['_meta'] = {'io.modelcontextprotocol/serverInfo': {
                    'name':'moh-frontier-controlled-tools', 'version':'2.3.0'}}
            return {'jsonrpc':'2.0','id':req_id,'result':result}

        params = request.get('params',{})
        meta = params.get('_meta') if isinstance(params,dict) else None
        modern = isinstance(meta,dict) and 'io.modelcontextprotocol/protocolVersion' in meta
        if modern:
            requested = meta['io.modelcontextprotocol/protocolVersion']
            if requested != '2026-07-28':
                return fail(-32022, 'Unsupported protocol version',
                            {'supported':['2026-07-28'], 'requested':requested})
            if not isinstance(meta.get('io.modelcontextprotocol/clientCapabilities'),dict):
                return fail(-32602,'Missing client capabilities')
        elif method == 'server/discover':
            return fail(-32602,'Discovery requires modern MCP per-request metadata')

        if method == 'server/discover' and modern:
            return answer({'supportedVersions':['2026-07-28'], 'capabilities':{'tools':{}},
                           'ttlMs':300000,'cacheScope':'private'},modern=True)

        if method == 'initialize' and not modern:
            if not isinstance(params,dict):
                return fail(-32602,'Invalid initialize params')
            self.legacy_initialized = True
            return answer({'protocolVersion':'2025-03-26', 'capabilities':{'tools':{}},
                           'serverInfo':{'name':'moh-frontier-controlled-tools','version':'2.3.0'}}, modern=False)

        if not modern and not self.legacy_ready:
            return fail(-32000,'Server not initialized')
        if method == 'ping' and not modern:
            return answer({},modern=False)
        if method == 'tools/list':
            if params and not isinstance(params,dict):
                return fail(-32602,'Invalid params')
            result = {'tools':TOOLS}
            if modern:
                result.update({'ttlMs':300000,'cacheScope':'private'})
            return answer(result,modern=modern)
        if method == 'tools/call':
            if not isinstance(params,dict) or not isinstance(params.get('name'),str):
                return fail(-32602,'Invalid params')
            return answer(self.call(params['name'], params.get('arguments',{})),modern=modern)
        return fail(-32601,'Method not found')


def serve_stdio(gateway: Gateway, stream_in: TextIO = sys.stdin, stream_out: TextIO = sys.stdout) -> None:
    """MCP JSON-RPC over stdio; stdout reserved for protocol traffic."""
    # Bounded readline avoids buffering arbitrarily large attacker messages.
    while True:
        line = stream_in.readline(MAX_LINE_BYTES + 1)
        if not line:
            break
        if len(line.encode('utf-8')) > MAX_LINE_BYTES or not line.endswith('\n'):
            # Consume any oversized message tail without executing it.
            while line and not line.endswith('\n'):
                line = stream_in.readline(MAX_LINE_BYTES + 1)
            result = {'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'Message exceeds limit'}}
        else:
            try:
                result = gateway.dispatch(json.loads(line))
            except (json.JSONDecodeError, UnicodeError):
                result = {'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'Parse error'}}
        if result is not None:
            stream_out.write(json.dumps(result, separators=(',', ':'))+'\n')
            stream_out.flush()
