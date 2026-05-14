# Bug Fix Example

## User request

The dashboard crashes when opening the settings tab.

## MOH AI SuperPowers response shape

```markdown
## Goal
Fix the dashboard crash when opening settings.

## Due diligence
Due diligence: PASS
Risk level: low
Reason: Localized UI bug fix, no data/auth/payment impact.
Verification planned: npm run build and manual settings-tab check.

## Files involved
- `src/pages/Dashboard.tsx` — renders settings tab
- `src/components/SettingsPanel.tsx` — likely crash location

## Plan
1. Inspect the settings render path.
2. Find the undefined/null access.
3. Add minimal guard or correct data initialization.
4. Verify with build and manual tab click.

## Verification
Verified with: npm run build
Verified with: manual browser flow
```
