---
name: sstack-mode
description: Investigate, design, prototype, or change solutions in the target repository using current platform contracts, Kizen-first design, and explicit behavioral proof.
---

# SStack mode

For implementation and review, read [engineering principles](references/engineering.md). Run the shared stack
gate with `control.py verify changed --base <actual-base> --jobs 2`; avoid
duplicating lint and tests that the selected suites already include.

For a project goal/backlog, use `sstack`; for a dispatched issue use
`sstack-engineer`. Ordinary questions and small direct edits need no new hierarchy.
Read skills at `tools/sstack/skills/<name>/SKILL.md` when not auto-discovered.

1. Restate the user outcome and observable acceptance. Read affected source and
   the nearest project instructions. Inspect git status and preserve unrelated work.
2. Find mechanics in code/current CLI docs; find intent in relevant history,
   handoffs, and user-linked conversations. Label historical evidence and unknowns.
   Refresh live state before planning deployment; do not invent rationale.
3. Read the affected feature in
   `tools/sstack/skills/sstack-verify/references/features.md`. If prerequisites are
   uncertain, run `control.py doctor <affected-suite>` from the repo root; do not
   repeat diagnostics when readiness is already established. An unrelated
   readiness failure need not block independent work.
4. Use the smallest appropriate workflow below, then `sstack-verify` before claiming
   success. For Kizen, read its `references/platform.md` before live interaction.

- **Investigate/teach:** trace input → workflow/code → stored result → UI. Explain
  established behavior, historical intent, and hypotheses separately.
- **Bug:** reproduce the failure, fix its cause, rerun the scenario and relevant
  regression tests. Prefer a meaningful failing test when a cheap local path exists.
- **Feature/architecture:** apply PM Kizen-first principles. Start with caller
  usage/data contracts, ownership, typed fields/relationships, identity, lifecycle,
  permissions, and failure semantics. Verify current platform capabilities.
- **Prototype:** answer a concrete uncertainty with a small disposable experiment
  and measurement. Staging writes still follow approval rules; a mock is not a
  live API. Compare alternatives when that evidence changes the design.
- **Multi-step work:** sequence independently verifiable outcomes. Revisit the
  design if real behavior invalidates it; avoid abstract plans without proof.
- **Maintain:** update feature commands and limits from actual source/runtime
  observations. Date evidence and distinguish local, live, and rendered results.

Use available host tools, not assumed Cursor skills, fixed models, or cloud VMs.
No automatic schedule or global merge permission is implied. Parallel code
isolation alone does not isolate a shared Kizen tenant.

## Focused playbooks

Load only the relevant playbook:
- [Research and context recovery](references/research.md) for understanding,
  historical rationale, teaching, and resuming prior work.
- [Design and prototypes](references/design.md) for usage-first contracts,
  competing candidates and experiments before implementation breakdown.
- [Learning](references/learn.md) for capturing proven lessons in tools and checks.
