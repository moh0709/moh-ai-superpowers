from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from frontier.evals.trace_report import analyze_trace, percentile_nearest_rank
from frontier.runtime.telemetry import AuditLog

class TraceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'work').mkdir()
        self.target=self.root/'trace.jsonl'
        self.writer=AuditLog(self.target,self.root/'work')

    def test_trace_aggregates_without_fake_model_usage(self):
        for tool,status in [('frontier.read_file','ok'),('frontier.apply_write','denied'),('frontier.preview_write','ok')]:
            self.writer.append(task_id='t',tool=tool,status=status,reason='',duration_ms=10.5)
        report=analyze_trace(self.target)
        self.assertEqual(report['events'],3)
        self.assertEqual(report['tool_denied'],1)
        self.assertAlmostEqual(report['denial_rate'],1/3)
        self.assertIsNone(report['tokens_in'])
        self.assertIsNone(report['task_success_rate'])
        self.assertIsNone(report['model_cost_usd'])

    def test_bad_duplicate_event_rejected(self):
        self.writer.append(task_id='t',tool='read',status='ok',reason='',duration_ms=1)
        record=self.target.read_text()
        self.target.write_text(record+record)
        with self.assertRaisesRegex(ValueError,'duplicate'): analyze_trace(self.target)

    def test_untrusted_token_injection_rejected(self):
        self.writer.append(task_id='t',tool='read',status='ok',reason='',duration_ms=1)
        row=json.loads(self.target.read_text())
        row['tokens_in']=999
        self.target.write_text(json.dumps(row))
        with self.assertRaisesRegex(ValueError,'untrusted usage'): analyze_trace(self.target)

    def test_percentile_nearest_rank(self):
        self.assertEqual(percentile_nearest_rank([1,2,3,4,5],95),5)
        self.assertEqual(percentile_nearest_rank([1,2,3,4,5],50),3)
        self.assertIsNone(percentile_nearest_rank([],95))

    def test_empty_trace(self):
        self.target.write_text('')
        self.assertEqual(analyze_trace(self.target)['events'],0)
        self.assertIsNone(analyze_trace(self.target)['denial_rate'])

if __name__=='__main__': unittest.main()
