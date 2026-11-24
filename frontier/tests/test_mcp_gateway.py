"""Adversarial and happy-path tests for the v2.3 MCP interface."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from frontier.runtime.controller import OperationDenied
from frontier.runtime.mcp_gateway import Gateway, HostTask, serve_stdio
from frontier.runtime.mcp_host import load_host_config
from frontier.runtime.telemetry import AuditLog


def git(repo, *args):
    res = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True, check=True)
    return res.stdout.strip()


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root = base / 'repo'
        self.root.mkdir()
        git(self.root, 'init', '-q')
        git(self.root, 'config', 'user.name', 'Test')
        git(self.root, 'config', 'user.email', 'test@example.com')
        (self.root/'src').mkdir()
        (self.root/'src'/'safe.py').write_text('print(1)\n')
        (self.root/'docs').mkdir()
        (self.root/'docs'/'public.md').write_text('hello\n')
        (self.root/'AGENTS.md').write_text('protected\n')
        git(self.root, 'add', '.')
        git(self.root, 'commit', '-qm', 'base')
        git(self.root, 'checkout', '-qb', 'frontier-test')
        self.commit = git(self.root,'rev-parse','HEAD')
        self.sha = hashlib.sha256(b'print(1)\n').hexdigest()
        self.traces = base / 'audit.jsonl'
        self.task = HostTask('pilot-1','Update harmless fixture',self.root,'frontier-test',
                             self.commit, frozenset({'src/safe.py','docs/public.md'}),
                             frozenset({'src/safe.py'}),max_calls=50)
        self.gateway = Gateway(self.task, AuditLog(self.traces,self.root))
        self.gateway.dispatch({'jsonrpc':'2.0','id':0,'method':'initialize','params':{}})
        self.gateway.dispatch({'jsonrpc':'2.0','method':'notifications/initialized'})

    def payload(self, name, **kwargs):
        res=self.gateway.call(name,kwargs)
        return json.loads(res['content'][0]['text']),res.get('isError',False)

    def test_mcp_initialize(self):
        r=self.gateway.dispatch({'jsonrpc':'2.0','id':1,'method':'initialize','params':{}})
        self.assertEqual(r['result']['serverInfo']['version'],'2.3.0')
        self.assertIn('tools',r['result']['capabilities'])

    def test_tools_list_limited(self):
        r=self.gateway.dispatch({'jsonrpc':'2.0','id':2,'method':'tools/list'})
        self.assertEqual([x['name'] for x in r['result']['tools']],
                         ['frontier.read_file','frontier.preview_write','frontier.apply_write'])

    def test_get_file_hash(self):
        out,error=self.payload('frontier.read_file',path='src/safe.py')
        self.assertFalse(error)
        self.assertEqual(out['sha256'],self.sha)
        self.assertEqual(out['content'],'print(1)\n')

    def test_preview_does_not_mutate(self):
        out,error=self.payload('frontier.preview_write',path='src/safe.py',content='print(2)\n',expected_sha256=self.sha)
        self.assertFalse(error)
        self.assertFalse(out['applied'])
        self.assertEqual((self.root/'src/safe.py').read_text(),'print(1)\n')
        self.assertEqual(out['verification_status'],'Not verified')

    def test_apply_write_and_unverified_receipt(self):
        out,error=self.payload('frontier.apply_write',path='src/safe.py',content='print(2)\n',expected_sha256=self.sha)
        self.assertFalse(error)
        self.assertTrue(out['applied'])
        self.assertEqual((self.root/'src/safe.py').read_text(),'print(2)\n')
        self.assertEqual(out['verification_status'],'Not verified')

    def test_stale_hash_denied(self):
        out,error=self.payload('frontier.apply_write',path='src/safe.py',content='print(3)\n',expected_sha256='0'*64)
        self.assertTrue(error)
        self.assertIn('unexpected_existing_contents',out['denied'])

    def test_no_write_outside_scope(self):
        out,error=self.payload('frontier.apply_write',path='docs/public.md',content='hack',expected_sha256=None)
        self.assertTrue(error)
        self.assertIn('write_outside_scope',out['denied'])

    def test_no_read_outside_scope(self):
        out,error=self.payload('frontier.read_file',path='AGENTS.md')
        self.assertTrue(error)
        self.assertIn('read_outside_scope',out['denied'])

    def test_traversal_denied(self):
        out,error=self.payload('frontier.read_file',path='../AGENTS.md')
        self.assertTrue(error)
        self.assertIn('read_outside_scope',out['denied'])

    def test_agent_cannot_change_risk_or_scope(self):
        out,error=self.payload('frontier.apply_write',path='src/safe.py',content='print(2)\n',
                               expected_sha256=self.sha,risk='low',trusted_scope=['AGENTS.md'])
        self.assertTrue(error)
        self.assertIn('invalid_write_arguments',out['denied'])

    def test_suspicious_content_denied(self):
        out,error=self.payload('frontier.apply_write',path='src/safe.py',content='PAYMENT_PASSWORD = 123',expected_sha256=self.sha)
        self.assertTrue(error)
        self.assertIn('sensitive_payload_requires_external_approval',out['denied'])

    def test_unknown_tool_denied_and_logged(self):
        out,error=self.payload('shell.execute',command='rm -rf .')
        self.assertTrue(error)
        self.assertIn('unknown_tool',out['denied'])
        events=[json.loads(x) for x in self.traces.read_text().splitlines()]
        self.assertEqual(events[-1]['status'],'denied')
        self.assertNotIn('rm -rf',str(events[-1]))

    def test_missing_args_denied(self):
        out,error=self.payload('frontier.apply_write',path='src/safe.py')
        self.assertTrue(error)
        self.assertIn('invalid_write_arguments',out['denied'])

    def test_invalid_arg_type_denied(self):
        out,error=self.gateway.call('frontier.apply_write',[]),True
        self.assertTrue(out['isError'])

    def test_host_disallows_main(self):
        task=HostTask('pilot-1','harmless',self.root,'main',self.commit,
                      frozenset({'src/safe.py'}),frozenset({'src/safe.py'}))
        with self.assertRaises(OperationDenied): task.validate()

    def test_host_wrong_branch(self):
        task=HostTask('pilot-1','harmless',self.root,'other',self.commit,
                      frozenset({'src/safe.py'}),frozenset({'src/safe.py'}))
        with self.assertRaises(OperationDenied) as ctx: task.validate()
        self.assertIn('wrong_branch',ctx.exception.reasons)

    def test_runtime_branch_changed(self):
        git(self.root,'checkout','--detach','-q')
        out,error=self.payload('frontier.apply_write',path='src/safe.py',content='print(2)\n',expected_sha256=self.sha)
        self.assertTrue(error)
        self.assertIn('wrong_branch',out['denied'])

    def test_head_changed(self):
        (self.root/'docs/public.md').write_text('later\n')
        git(self.root,'add','.')
        git(self.root,'commit','-qm','later')
        out,error=self.payload('frontier.apply_write',path='src/safe.py',content='print(2)\n',expected_sha256=self.sha)
        self.assertTrue(error)
        self.assertIn('base_commit_changed',out['denied'])

    def test_host_protected_scope(self):
        task=HostTask('pilot-1','harmless',self.root,'frontier-test',self.commit,
                      frozenset({'AGENTS.md'}),frozenset({'AGENTS.md'}))
        with self.assertRaises(OperationDenied) as ctx: task.validate()
        self.assertIn('protected_surface',ctx.exception.reasons)

    def test_config_inside_workspace_rejected(self):
        config=self.root/'config.json'
        config.write_text('{}')
        with self.assertRaises(ValueError): load_host_config(config)

    def test_host_config_cannot_expand_scope_via_tool(self):
        cfg=self.root.parent/'host.json'
        data={'task_id':'pilot-1','objective':'harmless','workspace':str(self.root),'branch':'frontier-test',
              'base_commit':self.commit,'read_scope':['src/safe.py'],'write_scope':['src/safe.py'],
              'audit_path':str(self.traces),'max_calls':2}
        cfg.write_text(json.dumps(data))
        gateway=load_host_config(cfg)
        result=gateway.call('frontier.read_file',{'path':'src/safe.py'})
        self.assertNotIn('isError',result)
        gateway.call('frontier.read_file',{'path':'src/safe.py'})
        denied=gateway.call('frontier.read_file',{'path':'src/safe.py'})
        self.assertTrue(denied['isError'])

    def test_audit_outside_workspace(self):
        with self.assertRaises(ValueError): AuditLog(self.root/'trace.jsonl',self.root)

    def test_audit_symlinked_parent_into_workspace_rejected(self):
        alias=self.root.parent/'trace-alias'
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError): AuditLog(alias/'trace.jsonl',self.root)

    def test_world_writable_config_rejected(self):
        cfg=self.root.parent/'host-world-writable.json'
        cfg.write_text('{}')
        cfg.chmod(0o666)
        with self.assertRaises(ValueError): load_host_config(cfg)

    def test_audit_leaks_no_source_content(self):
        self.payload('frontier.apply_write',path='src/safe.py',content='VERY_PRIVATE_CODE_12345',expected_sha256=self.sha)
        self.assertNotIn('VERY_PRIVATE_CODE_12345',self.traces.read_text())
        self.assertIn('"cost_usd":null',self.traces.read_text())

    def test_std_io_mcp_cycle(self):
        calls=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{}},
               {'jsonrpc':'2.0','method':'notifications/initialized'},
               {'jsonrpc':'2.0','id':2,'method':'tools/list'},
               {'jsonrpc':'2.0','id':3,'method':'tools/call',
                'params':{'name':'frontier.read_file','arguments':{'path':'src/safe.py'}}}]
        input_data=io.StringIO('\n'.join(json.dumps(x) for x in calls)+'\n')
        output_data=io.StringIO()
        serve_stdio(self.gateway,input_data,output_data)
        results=[json.loads(line) for line in output_data.getvalue().splitlines()]
        self.assertEqual(len(results),3)
        self.assertEqual(results[-1]['id'],3)
        self.assertNotIn('isError',results[-1]['result'])

    def test_malformed_json_is_protocol_error(self):
        inp=io.StringIO('{oops\n')
        out=io.StringIO()
        serve_stdio(self.gateway,inp,out)
        self.assertEqual(json.loads(out.getvalue())['error']['code'],-32700)

    def test_notifications_never_execute(self):
        result=self.gateway.dispatch({'jsonrpc':'2.0','method':'tools/call','params':{'name':'frontier.apply_write',
            'arguments':{'path':'src/safe.py','content':'print(2)\n','expected_sha256':self.sha}}})
        self.assertIsNone(result)
        self.assertEqual((self.root/'src/safe.py').read_text(),'print(1)\n')

    def test_invalid_message_errors(self):
        self.assertEqual(self.gateway.dispatch(None)['error']['code'],-32600)
        self.assertEqual(self.gateway.dispatch({'jsonrpc':'2.0','id':1,'method':'other'})['error']['code'],-32601)
        self.assertEqual(self.gateway.dispatch({'jsonrpc':'2.0','id':1,'method':'tools/call','params':[]})['error']['code'],-32602)

    def test_symlink_read_rejected(self):
        (self.root/'docs/public.md').unlink()
        (self.root/'docs/public.md').symlink_to(self.root/'AGENTS.md')
        out,error=self.payload('frontier.read_file',path='docs/public.md')
        self.assertTrue(error)
        self.assertIn('symlink_not_allowed',out['denied'])

    def test_expected_hash_is_required(self):
        out,error=self.payload('frontier.apply_write',path='src/safe.py',content='print(2)\n',expected_sha256=None)
        self.assertTrue(error)
        self.assertIn('unexpected_existing_contents',out['denied'])

    def test_audit_append_multiple_events(self):
        self.payload('frontier.read_file',path='src/safe.py')
        self.payload('frontier.preview_write',path='src/safe.py',content='print(2)\n',expected_sha256=self.sha)
        lines=self.traces.read_text().splitlines()
        self.assertEqual(len(lines),2)
        self.assertEqual(len({json.loads(x)['event_id'] for x in lines}),2)

if __name__ == '__main__': unittest.main()

# This process-level smoke check exercises actual JSON-RPC stdio plumbing,
# as opposed to direct in-process calls. It does not use a live language model.
class MCPExternalProcessTests(unittest.TestCase):
    setUp = GatewayTests.setUp
    def test_external_process_stdout_protocol(self):
        cfg=self.root.parent/'external-host.json'
        cfg.write_text(json.dumps({
            'task_id':'pilot-1','objective':'Update harmless fixture',
            'workspace':str(self.root),'branch':'frontier-test','base_commit':self.commit,
            'read_scope':['src/safe.py'], 'write_scope':['src/safe.py'],
            'audit_path':str(self.traces),'max_calls':50,
        }))
        calls=[
            {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26'}},
            {'jsonrpc':'2.0','method':'notifications/initialized'},
            {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'frontier.read_file','arguments':{'path':'src/safe.py'}}},
            {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'frontier.apply_write','arguments':{'path':'src/safe.py','content':'print(4)\n','expected_sha256':self.sha}}},
        ]
        from frontier import __file__ as frontier_file
        project_root=str(Path(frontier_file).parent.parent)
        p=subprocess.run([sys.executable,'-m','frontier.runtime.mcp_host','--host-config',str(cfg)],
                         input='\n'.join(json.dumps(c) for c in calls)+'\n',
                         stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=10,
                         cwd=project_root)
        self.assertEqual(p.returncode,0, p.stderr)
        result=[json.loads(x) for x in p.stdout.splitlines()]
        self.assertEqual(len(result),3)
        self.assertEqual(result[-1]['result']['isError'] if 'isError' in result[-1]['result'] else False,False)
        self.assertEqual((self.root/'src/safe.py').read_text(),'print(4)\n')
        self.assertEqual(len(self.traces.read_text().splitlines()),2)
