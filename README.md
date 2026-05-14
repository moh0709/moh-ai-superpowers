# MOH AI SuperPowers

**MOH AI SuperPowers** is a reusable AI engineering skill framework for AI coding agents.

It combines:

1. **Superpowers-style workflow discipline** — structured planning, execution, review, and verification.
2. **Karpathy-style coding discipline** — simplicity, surgical edits, explicit assumptions, and verifiable goals.
3. **MOH governance rules** — exact file paths, safe execution, approval gates, main-branch discipline, and honest verification.
4. **Due diligence gates** — proceed only when scope, risk, verification, and rollback checks pass.

The purpose is to make AI coding agents behave like careful senior engineers: productive, precise, safe, and verifiable.

---

## Core principle

> Plan clearly. Edit surgically. Verify honestly. Preserve working systems. Never fake certainty.

---

## Why this exists

Most AI coding failures come from the same patterns:

- editing before understanding
- changing too much
- inventing architecture
- refactoring unrelated code
- claiming success without verification
- deleting or overwriting important work
- ignoring project-specific rules
- proceeding without due diligence

MOH AI SuperPowers gives the agent an operating system for avoiding those failures.

---

## Repository structure

```text
moh-ai-superpowers/
├── README.md
├── LICENSE
├── AGENTS.md
├── CLAUDE.md
├── skills/
│   └── moh-ai-superpowers/
│       └── SKILL.md
├── docs/
│   ├── DUE_DILIGENCE.md
│   ├── GOVERNANCE.md
│   ├── VERIFICATION.md
│   └── OPERATING_MODES.md
├── templates/
│   ├── task-brief.md
│   ├── verification-report.md
│   └── implementation-plan.md
├── examples/
│   ├── bug-fix-example.md
│   └── feature-example.md
└── .github/
    └── ISSUE_TEMPLATE/
        ├── bug_report.md
        └── feature_request.md
```

---

## Installation

### Option 1 — Use as an agent instruction file

Copy `AGENTS.md` into the root of your project.

### Option 2 — Use with Claude Code

Copy `CLAUDE.md` into the root of your project.

### Option 3 — Use as a skill

Copy this folder into your agent skills directory:

```text
skills/moh-ai-superpowers/SKILL.md
```

### Option 4 — Use inside another repo

Add this repository as a submodule or vendor folder:

```bash
git submodule add https://github.com/moh0709/moh-ai-superpowers.git tools/moh-ai-superpowers
```

---

## Activation rule

Use this skill when the user asks for:

- code implementation
- debugging
- refactoring
- project audit
- architecture review
- planning
- AI agent execution prompt
- repository cleanup
- deployment-related changes
- database/auth/payment/security-sensitive work

For trivial answers, use judgment and keep the response lightweight.

---

## Compatibility

This skill is intentionally tool-agnostic and can be adapted for:

- ChatGPT / Codex-style agents
- Claude Code
- GitHub Copilot coding agent
- Cline
- Cursor
- OpenCode
- Gemini CLI
- Kilo Code
- custom MCP or OpenClaw-style agents

---

## Non-negotiable rules

1. Always mention exact file paths when changing code.
2. Inspect before editing when project access is available.
3. Do not invent file contents.
4. Make the smallest useful change.
5. Ask approval before destructive actions or large refactors.
6. Verify before claiming completion.
7. Say clearly when something was not verified.
8. Provide full file code when requested.
9. Preserve existing working behavior.
10. Respect `main`-branch-only policies when specified.
11. Do not proceed unless due diligence passes for meaningful or risky work.

---

## Recommended project-level instruction

Add this to your project prompt or agent boot instruction:

```text
Use MOH AI SuperPowers for all engineering work. Follow the workflow, governance rules, file/path discipline, due diligence gates, approval gates, and verification standard. Do not claim completion without evidence.
```

---

## License

MIT
