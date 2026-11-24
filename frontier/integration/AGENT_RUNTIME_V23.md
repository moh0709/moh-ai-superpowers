# MOH Frontier Harness v2.3 — controlled coding-agent gateway

## Actual implementation status

The `frontier.runtime.mcp_host` program is an MCP server with three narrowly scoped tools. It speaks both legacy MCP `2025-03-26` (with initialization) and modern MCP `2026-07-28` (`server/discover`, per-request metadata). The server can accept tool requests from Codex/Claude Code or any compatible MCP client. **Only a local simulated MCP client and process-level protocol exchange have been tested. Neither Codex nor Claude Code was available in the test environment.**

**Do not mistake an MCP server for a sandbox.** A coding agent that also has shell, GitHub write, filesystem, browser, web or arbitrary-code tools can bypass this gateway. The host must deny those other tools at the operating-system or agent-platform level; tests of this gateway do not enforce their absence. Before production use, deploy the agent and verifier in isolated workloads with least privilege, read-only protected grading assets, no access to secrets, constrained egress, and a trusted host-owned gateway.

## Paths added in v2.3

- `frontier/runtime/mcp_gateway.py` — MCP protocol and authorization boundary
- `frontier/runtime/mcp_host.py` — host-only CLI configuration and stdio server
- `frontier/runtime/telemetry.py` — metadata-only local audit trail
- `frontier/evals/trace_report.py` — aggregate local tool calls without inventing model usage
- `frontier/tests/test_mcp_gateway.py` — scoped write, path, branch, protocol, audit, process tests
- `frontier/tests/test_mcp_modern.py` — modern protocol test cases
- `frontier/tests/test_trace_report.py` — trace validation and summary tests

Existing v2.2 paths remain unchanged. Do not replace the established `skills/moh-ai-superpowers/SKILL.md`, `AGENTS.md`, or `CLAUDE.md` automatically.

## Create one isolated pilot task

The workspace below must be a **disposable Git checkout on a dedicated non-main branch**, with an existing commit. Create a host-controlled JSON file outside the workspace, owned by an account the agent cannot modify, for example `/trusted/moh-pilot.json`:

```json
{
  "task_id": "pilot-001",
  "objective": "Fix one isolated low-risk utility",
  "workspace": "/isolated/pilot-repo",
  "branch": "frontier-pilot",
  "base_commit": "REPLACE_WITH_ACTUAL_40_CHARACTER_GIT_COMMIT_SHA",
  "read_scope": ["src/utility.py", "tests/test_utility.py"],
  "write_scope": ["src/utility.py"],
  "audit_path": "/trusted/frontier-events.jsonl",
  "max_calls": 30
}
```

The server **does not** accept changed task scope, risk, objective, approved branch, or committed revision from the agent. `apply_write` requires `expected_sha256` from the current file content (`null` if the file is absent). The controller performs an additional check immediately before replacing a target. It returns `verification_status: "Not verified"` even if the write succeeds.

Run from the repository root with Python 3.11+:

```bash
python -m frontier.runtime.mcp_host --host-config /trusted/moh-pilot.json
```

Stdio is reserved for JSON-RPC; operational errors go to stderr.

## How to register with a coding client

**Only configure this inside a genuinely restricted agent sandbox.** MCP registration does not revoke built-in tools.

Codex CLI:

```bash
codex mcp add moh-frontier -- python -m frontier.runtime.mcp_host --host-config /trusted/moh-pilot.json
```

Claude Code:

```bash
claude mcp add --transport stdio moh-frontier -- python -m frontier.runtime.mcp_host --host-config /trusted/moh-pilot.json
```

Command syntax follows the vendors' current MCP documentation. These commands have **not** been executed against the actual clients in this environment; verify with their respective `mcp list` command. To prevent misconfiguration, the host should inject the correct absolute Python executable, package path and host config path.

## Testing and trace reports

```bash
python -W error::ResourceWarning -m unittest discover -s frontier/tests -q
python -m compileall -q frontier
python -m frontier.evals.compare_gates
python -m frontier.evals.trace_report /trusted/frontier-events.jsonl
```

The trace report includes tool invocation count, denied calls, denial ratio and p50/p95 tool latency. Model tokens, billing, actual coding-task success and return on investment are explicitly **null** until measured from independently trusted sources.

## Verification and promotion gates

- Only the trusted controller selects and pins test commands; the agent must not supply arbitrary test argv.
- The separate v2.2 `TrustedTestExecutor` and signed evidence verifier remain available; neither is exposed as an agent-writable MCP tool.
- No real task is declared Verified based on a successful write or MCP response.
- Never allow agent writes to benchmark graders, governance, hidden tasks, model secrets, payment/auth, or production systems.
- Do not auto-merge or deploy. Self-improvement experiments remain proposal-only until verified on held-out tasks and approved.

## Known limitations / P2 requirements

1. This server is not an OS sandbox and does not interpose other tools.
2. It supports only single-file mutations; there is no atomic multi-file transaction or rollback manager.
3. It does not authenticate a local client process independently; deploy it only in an OS-enforced trusted context.
4. Local JSONL audit metadata is not an immutable remote audit service.
5. Test executor process isolation, provenance of frozen tests, and immutable receipts require further host integration.
6. No actual Codex/Claude model tasks were run: model pass@1, model latency, tokens and cost have no measured baseline.
7. Modern MCP support is tested by protocol fixtures, not a third-party SDK conformance suite.
