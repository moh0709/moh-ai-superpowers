# Feature Example

## User request

Add a button that exports current table data to CSV.

## MOH AI SuperPowers response shape

```markdown
## Goal
Add CSV export for the current table view.

## Due diligence
Due diligence: PASS
Risk level: low
Reason: Localized frontend utility and button, no destructive action or sensitive logic.
Verification planned: npm run build and manual CSV download check.

## Files involved
- `src/components/DataTable.tsx` — existing table component
- `src/utils/exportCsv.ts` — new utility file

## Plan
1. Inspect table data structure.
2. Add a small CSV utility.
3. Add export button.
4. Verify build and manual CSV download.

## Verification
Verified with: npm run build
Manual check: clicked Export CSV and confirmed file download
```
