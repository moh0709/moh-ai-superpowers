# MOH Frontier Harness — v2.2 P1 controller prototype

**Status: experimental, locally verified components. Not deployed. Not a production sandbox.**

This folder is a drop-in, **opt-in** extension of MOH AI SuperPowers v1.1.0. It adds a narrow, host-owned write controller, controller-signed short-lived verification receipts, replay protection, protected read/write surfaces, an independent fixed-command test adapter, adversarial unit tests, and a reproducible comparison with the P0 v2.1 baseline.

## Exact modules

| File | Role |
|---|---|
| `frontier/runtime/gate.py` | Mandatory structured-task preflight, path and intent restrictions |
| `frontier/runtime/controller.py` | Pinned-commit, hash-checked, single-file write adapter; dry-run by default |
| `frontier/runtime/verifier.py` | Host-owned fixed-command unittest execution and scoped workspace hashing |
| `frontier/runtime/evidence_v2.py` | HMAC-signed short-lived receipts, durable SQLite replay ledger |
| `frontier/runtime/score.py` | Paired task-cluster benchmark scorer (no live model results yet) |
| `frontier/evals/compare_gates.py` | 14 deliberately targeted P0-versus-P1 regression fixtures |
| `frontier/evals/baselines/gate_v2_1.py` | Frozen reference gate, **never used as policy in production** |
| `frontier/tests/` | Unit, adversarial and end-to-end **local fixture** tests |
| `frontier/docs/TRUST_BOUNDARIES.md` | Security assumptions, explicit limitations and promotion gates |
| `frontier/integration/frontier-tests.example.yml` | Opt-in read-only CI example; not active unless installed by owner |

## Run the integrity tests

Requirements: **Python 3.10+**, Git, POSIX for file-write integration tests. Runtime uses the Python standard library; no LLM account, API key, or live project is needed.

From the repository root:

```bash
python -m unittest discover -s frontier/tests -q
python -m compileall -q frontier
python -m frontier.evals.compare_gates
```

Optional branch coverage:

```bash
coverage run --branch --source=frontier/runtime -m unittest discover -s frontier/tests -q
coverage report -m
```

## Minimal scoped controller usage (trusted host process only)

```python
from pathlib import Path
import hashlib
from frontier.runtime.controller import ScopedController

root = Path('/absolute/path/to/isolated/git-worktree')
controller = ScopedController(root, frozenset({'src/example.py'}))
# Host obtains the complete pinned HEAD hash independently, e.g. `git rev-parse HEAD`.
head = 'a' * 40  # PLACEHOLDER: replace with actual HEAD SHA
original = (root / 'src/example.py').read_bytes()
task = {
    'task_id': 'T-100', 'objective': 'Change a harmless example',
    'base_commit': head, 'risk': 'low',
    'operations': [{
        'type': 'write_file', 'path': 'src/example.py',
        'content': 'print(2)\n',
        'expected_sha256': hashlib.sha256(original).hexdigest(),
    }],
}
receipt = controller.write(task, dry_run=True)   # does not write
# After human/host authorization, controller.write(task, dry_run=False) writes.
# This write receipt is always "Not verified"; tests and independent receipt required.
```

The task's `approved`, `trusted_scope`, or `authority` fields are never permissions. **The host**, not an agent, supplies trusted scope and the signing key.

## What this is not

- Not an OS sandbox or protection against an agent with direct shell, file, GitHub, or browser-write access.
- Not multi-file atomicity, deployment authorization, secrets safety, or production transaction control.
- Not independent if the agent can edit tests, verifier, signing key, replay database, or evaluation suite.
- Not a performance benchmark of AI models. No real model execution/cost traces have been collected.
- Not a live self-improving system. Proposals are still human-reviewed and no autonomous promotion exists.

**Before any production use:** connect through an actual isolated host that exclusively mediates agent tools, separate privileged verifier, immutable test ownership, and protected host secrets. Refer to `frontier/docs/TRUST_BOUNDARIES.md`.
