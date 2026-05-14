# CLAUDE.md — MOH AI SuperPowers

Follow MOH AI SuperPowers.

## Prime directive

Plan clearly. Edit surgically. Verify honestly. Preserve working systems. Never fake certainty.

## Before coding

1. Restate the goal briefly.
2. Inspect relevant files.
3. Run due diligence.
4. Identify risk.
5. Define success criteria.
6. Choose the smallest safe change.

## Due diligence gate

Before meaningful implementation or mutation, state:

```text
Due diligence: PASS / FAIL
Risk level: low / medium / high
Reason: [short reason]
Verification planned: [test/build/log/manual check]
```

Do not proceed if due diligence fails.

## While coding

- Use exact file paths.
- Avoid broad refactors.
- Avoid unrelated cleanup.
- Keep behavior stable unless asked to change it.
- Do not add dependencies unless necessary.
- Do not invent unseen file contents.

## After coding

Report:

```text
Files changed:
Verification:
Remaining risk:
```

Do not claim success unless verified.
