"""Aggregate trusted-local gateway traces; do not infer model tokens or success.

A gateway trace reports tool usage only, not developer-task correctness. For a
proper v1.1 versus v2.3 comparison, add an independent task grader and a billing
source and preserve the task-level pairing. Missing metrics remain null.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics


def percentile_nearest_rank(values: list[float], percent: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    import math
    return ordered[max(0, math.ceil(percent/100*len(ordered))-1)]


def analyze_trace(path: Path) -> dict:
    records=[]
    unique=set()
    for index,line in enumerate(Path(path).read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        row=json.loads(line)
        required={'schema','event_id','unix_ms','task_id','tool','status','reason','duration_ms',
                  'tokens_in','tokens_out','cost_usd'}
        if not isinstance(row,dict) or set(row)!=required or row['schema']!='moh-frontier-tool-trace-v1':
            raise ValueError(f'invalid trace schema at line {index}')
        if row['event_id'] in unique:
            raise ValueError('duplicate audit event')
        unique.add(row['event_id'])
        if row['status'] not in ('ok','denied'):
            raise ValueError('unexpected status')
        d=row['duration_ms']
        if isinstance(d,bool) or not isinstance(d,(int,float)) or not (0 <= d < 1e9):
            raise ValueError('invalid duration')
        if any(row[k] is not None for k in ('tokens_in','tokens_out','cost_usd')):
            raise ValueError('untrusted usage data in gateway trace')
        records.append(row)
    values=[r['duration_ms'] for r in records]
    results={
        'source':str(path),'schema':'moh-frontier-trace-summary-v1',
        'events':len(records),'tool_ok':sum(r['status']=='ok' for r in records),
        'tool_denied':sum(r['status']=='denied' for r in records),
        'denial_rate':(sum(r['status']=='denied' for r in records)/len(records) if records else None),
        'mean_tool_ms':round(statistics.mean(values),3) if values else None,
        'p50_tool_ms':percentile_nearest_rank(values,50),
        'p95_tool_ms':percentile_nearest_rank(values,95),
        'task_success_rate':None,'tokens_in':None,'tokens_out':None,'model_cost_usd':None,
        'distinct_tasks':len({r['task_id'] for r in records}),
        'caution':'Tool call success is not coding-task success; no agent-model metrics captured',
    }
    return results


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument('trace',type=Path)
    args=ap.parse_args()
    print(json.dumps(analyze_trace(args.trace),indent=2,sort_keys=True))

if __name__=='__main__':
    main()
