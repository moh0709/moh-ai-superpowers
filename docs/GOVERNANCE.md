# Governance

MOH AI SuperPowers uses governance rules to prevent AI coding agents from creating uncontrolled project changes.

## File/path governance

Every code change must identify:

- path
- filename
- whether the file exists
- action type
- risk level

Required format:

```text
File: path/to/file.ext
Existing file: yes/no
Action: add / replace / modify / delete
Risk level: low / medium / high
```

## Approval gates

Approval is required before:

- deleting files
- moving files in bulk
- changing database schema
- modifying auth/payment/security/deployment logic
- force-pushing
- broad refactoring
- changing production configuration
- executing AI-driven file operations at scale

## Branch policy

If a project states that work must happen directly on `main`, agents must not create long-lived feature branches.

If no such policy exists, short-lived branch/PR workflow is acceptable.

## Destructive action policy

Destructive actions must be:

1. explained
2. risk-rated
3. backed up where possible
4. explicitly approved
5. reversible where possible

## Existing behavior preservation

Existing working behavior must be preserved unless the requested task explicitly changes it.

When changing behavior, document:

- what changes
- why it changes
- what risk it introduces
