"""Modern July 2026 protocol compatibility tests."""
import json
import tempfile
from pathlib import Path
import unittest

from frontier.runtime.mcp_gateway import Gateway,HostTask
from frontier.runtime.telemetry import AuditLog
from frontier.tests.test_mcp_gateway import git


META={'io.modelcontextprotocol/protocolVersion':'2026-07-28',
      'io.modelcontextprotocol/clientCapabilities':{},
      'io.modelcontextprotocol/clientInfo':{'name':'test-client','version':'0.1'}}


class MCPModernTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.repo=root/'repo'
        self.repo.mkdir()
        git(self.repo,'init','-q')
        git(self.repo,'config','user.name','Test')
        git(self.repo,'config','user.email','test@example.com')
        (self.repo/'safe.py').write_text('pass\n')
        git(self.repo,'add','.')
        git(self.repo,'commit','-qm','base')
        git(self.repo,'checkout','-qb','mcp-modern')
        commit=git(self.repo,'rev-parse','HEAD')
        task=HostTask('t1','harmless example',self.repo,'mcp-modern',commit,
                      frozenset({'safe.py'}),frozenset({'safe.py'}))
        self.gateway=Gateway(task,AuditLog(root/'audit.jsonl',self.repo))

    def req(self,method,meta=META,params=None):
        return self.gateway.dispatch({'jsonrpc':'2.0','id':1,'method':method,
                                      'params':{'_meta':meta,**(params or {})}})

    def test_modern_discovery_without_legacy_initialize(self):
        r=self.req('server/discover')['result']
        self.assertEqual(r['resultType'],'complete')
        self.assertEqual(r['supportedVersions'],['2026-07-28'])
        self.assertEqual(r['cacheScope'],'private')
        self.assertIn('io.modelcontextprotocol/serverInfo',r['_meta'])

    def test_modern_tool_list_has_cache_metadata(self):
        r=self.req('tools/list')['result']
        self.assertEqual(r['resultType'],'complete')
        self.assertEqual(r['ttlMs'],300000)
        self.assertEqual(len(r['tools']),3)

    def test_modern_tool_call_without_initialize(self):
        r=self.req('tools/call',params={'name':'frontier.read_file','arguments':{'path':'safe.py'}})['result']
        self.assertEqual(r['resultType'],'complete')
        self.assertIn('sha256',r['content'][0]['text'])
        self.assertFalse(r.get('isError',False))

    def test_missing_client_capabilities_denied(self):
        r=self.req('tools/list',meta={'io.modelcontextprotocol/protocolVersion':'2026-07-28'})
        self.assertEqual(r['error']['code'],-32602)

    def test_unknown_protocol_refused(self):
        r=self.req('tools/list',meta={'io.modelcontextprotocol/protocolVersion':'2027-01-01',
                                      'io.modelcontextprotocol/clientCapabilities':{}})
        self.assertEqual(r['error']['code'],-32022)
        self.assertEqual(r['error']['data']['supported'],['2026-07-28'])

    def test_legacy_uninitialized_tool_call_rejected(self):
        r=self.gateway.dispatch({'jsonrpc':'2.0','id':4,'method':'tools/call',
            'params':{'name':'frontier.read_file','arguments':{'path':'safe.py'}}})
        self.assertEqual(r['error']['code'],-32000)

    def test_legacy_requires_initialized_notification(self):
        self.gateway.dispatch({'jsonrpc':'2.0','id':1,'method':'initialize','params':{}})
        r=self.gateway.dispatch({'jsonrpc':'2.0','id':2,'method':'tools/list'})
        self.assertEqual(r['error']['code'],-32000)
        self.gateway.dispatch({'jsonrpc':'2.0','method':'notifications/initialized'})
        self.assertEqual(len(self.gateway.dispatch({'jsonrpc':'2.0','id':3,'method':'tools/list'})['result']['tools']),3)

    def test_removed_ping_not_accepted_modern(self):
        r=self.req('ping')
        self.assertEqual(r['error']['code'],-32601)

    def test_discovery_without_modern_metadata_rejected(self):
        r=self.gateway.dispatch({'jsonrpc':'2.0','id':3,'method':'server/discover'})
        self.assertEqual(r['error']['code'],-32602)

if __name__=='__main__': unittest.main()
