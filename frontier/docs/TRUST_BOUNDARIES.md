# Threat model and promotion gates — MOH Frontier v2.2

## Trust boundaries

**Agent process: UNTRUSTED.** It can supply a structured task and propose content, but has no authority to grant approvals, choose allowed file scope, access verifier secrets, modify policy, change test suites, or run arbitrary tools. The model's assertions do not count as evidence.

**Host controller: TRUSTED FOR POLICY.** It must hold the trusted scope and dispatch exclusively through `ScopedController`. A task manifest is *data*, not authorization. The controller preflights the path, scope, risk, intent, pinned repository root and expected file digest, then writes a single file through no-follow directory descriptors. This does not defend against an agent that can directly invoke OS file APIs or other write-capable connectors.

**Verifier: INDEPENDENT ONLY WHEN ACTUALLY ISOLATED.** It must own its test suites, allowed command profiles, private HMAC key and evidence directory. The prototype can launch a fixed unittest command but cannot guarantee the test code is safe; test code requires an actual OS sandbox with least-privilege access. The signer needs to attest results from its own measurement, not data supplied by the agent.

**Replay ledger: HOST-OWNED.** A SQLite store protects against using the same signed receipt twice or reusing a run ID. It must remain outside the agent-controlled filesystem and survive process restarts; do not reset it during a task.

**Evaluation suite: PROTECTED.** The archived v2.1 gate is for reproducible comparisons only. Agents must not modify the grader, held-out tasks, benchmark provenance, or promotion thresholds.

**Human governance: REQUIRED.** Auth, payments, schema migration, deployment, secrets, file deletion, force push, self-modification of policies or verifier code, and protected changes all require explicit approval through a separate trusted channel. A model-written `approved: true` has no effect.

## Known technical limitations

- The controller only supports **one low-risk file write per call**; there is no multi-file atomic transaction or automatic rollback.
- Path/keyword checks cannot understand every semantic security impact; false negatives and false positives are possible.
- Hash-check-then-replace has residual concurrency risks if other writers have access to the workspace. Only an exclusive OS-isolated worktree is suitable for higher assurance.
- Test stdout can be fabricated if the test suite is untrusted. Production verification must use pinned, independent suites, validated runner exit status and isolated execution.
- HMAC is a receipt format, not proof of test truth or secure key custody.
- Signed evidence expires after up to 10 minutes and must be checked for task, commit, workspace and issuer binding. Timing depends on a trusted host clock.
- The verifier currently hashes scoped paths, not a full hermetic dependency or environment image. Real evaluation needs immutable environments and runtime provenance.
- Benchmark `score.py` handles paired tasks and task-cluster bootstrapping; it does not yet collect or attest real AI-agent traces.

## Go/no-go requirements for integrated P2

| Requirement | P1 result | Minimum P2 acceptance |
|---|---|---|
| Safe write adapter | Tested locally | Host mediates **all** agent mutations including GitHub and shell |
| Agent privilege separation | Not established | Isolated OS credential and namespace/container per task |
| Test executor | Fixed-command fixture tested | Tests maintained and invoked outside writable workspace |
| Evidence signer | Unit tested | Non-exportable/private signer key; no agent path to signer or ledger |
| Replay resistance | SQLite unit tested | Persistent, backed-up ledger under protected host identity |
| Workspace integrity | Scoped hash tested | Snapshot of full effective sources/dependencies |
| Live AI benchmark | Not run | Pinned models, token/cost traces, real tasks, private holdout |
| Automatic self-evolution | Not enabled | Candidate-only proposals, frozen graders and manual promotion |
| Protected operation/production changes | Denied by P1 prototype | Separate approval, dry-run, rollback, CI/canary and human signoff |

**No merges, deployments, or self-promotion are authorized by passing these P1 tests.**
