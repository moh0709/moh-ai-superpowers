# Due Diligence Pass Rule

MOH AI SuperPowers requires a hard due diligence gate before meaningful execution.

## Rule

No implementation, mutation, deployment, deletion, database change, payment change, authentication change, or production-impacting work may proceed unless due diligence passes.

## Required output

```text
Due diligence: PASS / FAIL
Risk level: low / medium / high
Reason: [short reason]
Verification planned: [test/build/log/manual check]
```

## Checklist

| Check | Requirement |
|---|---|
| Goal clarity | The requested outcome is understood |
| Scope clarity | The affected files/systems are identified or inspection is planned |
| Risk classification | Risk level is classified as low, medium, or high |
| Destructive action check | No destructive action will occur without explicit approval |
| Security check | Auth, permissions, secrets, payments, and user data impact are considered |
| Data safety check | Database/file/user data risk is understood |
| Existing behavior check | Existing working behavior is preserved unless intentionally changed |
| Verification path | A realistic verification method is defined |
| Rollback path | A rollback or recovery path exists for medium/high-risk changes |
| User approval | Required approvals are obtained before risky work |

## Fail behavior

If due diligence fails, the agent must not proceed.

Use:

```text
Due diligence: FAIL
Blocking reason: [what is missing or unsafe]
Required before proceeding: [specific action or approval needed]
```

## Hard stop conditions

Stop and ask for approval or missing information if:

- the task can delete or overwrite data
- the task can affect production
- the task changes payment, auth, database schema, permissions, or secrets
- the current file contents are unknown and exact edits are required
- the verification path is impossible but the user expects a completed claim
- the rollback path is missing for medium/high-risk work
