# Verification Standard

The agent must not claim completion without verification evidence.

## Valid verification

Examples:

```text
Verified with: npm run build
Verified with: npm test
Verified with: pytest
Verified with: npx tsc --noEmit
Verified with: manual browser flow
Verified with: log inspection
```

## If verification is unavailable

Use:

```text
Not verified because: [reason]
```

## Status vocabulary

Use precise terms:

- Implemented
- Verified
- Partially verified
- Not verified
- Blocked
- Needs approval
- Inferred

Avoid vague claims like “should work” unless clearly marked as unverified.

## Verification menu

Frontend:

```bash
npm run build
npm test
npm run lint
npx tsc --noEmit
npx playwright test
```

Backend Node:

```bash
npm test
npm run build
npm run lint
npx prisma validate
npx prisma migrate status
```

Python:

```bash
pytest
python -m pytest
ruff check .
mypy .
python -m compileall .
```

General:

```bash
git diff --check
git status
docker compose config
```
