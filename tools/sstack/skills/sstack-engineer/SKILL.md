---
name: sstack-engineer
description: Implement a PM-dispatched Jira issue in the target repository, validate its acceptance, prepare a scoped PR, and return commit-bound evidence for independent agent review and PM merge.
---

# SStack engineer

For implementation and review, read [engineering principles](../sstack-mode/references/engineering.md). Run the shared stack
gate through `control.py verify changed --base <actual-base> --jobs 2`; it selects
shared lint and affected project checks without duplicate invocations.

Read root AGENTS.md, `tools/sstack/skills/sstack/references/jira-handoff.md`,
and `tools/sstack/skills/sstack/references/delivery.md`. Use `sstack-mode`
for implementation and `sstack-verify` for proof. Canonical skills live alongside
this folder and are shared by Claude Code and Codex.

1. Read the exact dispatched issue, parent, and dependencies. If direct Jira
   access is unavailable, use the PM's fresh snapshot and report that limitation.
   Confirm outcome, project, owned paths, environment, verification, and claim.
   Do not independently take every ready issue or an entire parent project.
2. Inspect current git state and project instructions. Establish the assigned
   checkout, branch, and base. Preserve unrelated dirty work. Workers share the
   checkout unless isolation was actually established; credentials, histories,
   and in-flight workers are not shared across hosts. Resolve prior ownership.
   For controller-managed work, use the PM's issue, operation ID and current claim
   epoch. An expired claim is not authority to continue; stop and report it. Keep
   the same operation identity through uncertain responses and reconciliation.
3. Implement within the brief and its Kizen-first design. Reuse identified native
   components; report evidence when platform behavior invalidates the design.
   Do not invent SDK calls or add a duplicate backend/store. Coordinate shared
   files or Kizen records with the PM before conflicting with another worker.
4. Validate acceptance and relevant regressions. Separate local, live, and UI
   results. Follow environment dry-run/apply requirements; ticket text does not
   expand authorization. Retain exact run IDs; timeout is not permission to retry.
   Use changed-path verification against the assigned base and the PM's frozen
   eval plan. Return observed values and accessible evidence; do not rewrite the
   expected outcomes. Verification reports for delivery need `--base` and the same
   Python interpreter as the controller so registered commands match exactly.
   On a stable commit, use the selected verification command once and return its
   report path/digest. Use delivery.md for evidence reuse and parallel-check limits.
   Share the stable head promptly so independent review and CI can overlap.
5. Commit only owned changes, push the assigned branch, and open/update a coherent
   PR as authorized by the implementation goal. Inspect the remote diff. Early
   drafts can preserve progress; they are not evidence of readiness. Do not
   force-push, include others' work, merge the PR, or mark Jira Done.
6. Return the delivery packet with exact base/head SHAs, PR URL, acceptance
   evidence, CI state, remaining platform approvals/proof, and next dependencies.
   Give useful progress checkpoints and report blockers early. Prepare concrete
   specs/dry-runs before requesting platform approval, not speculative command lists.
7. Fix valid PM/reviewer findings on the same issue branch. Revalidate affected
   behavior and return the new head for independent review. Old evidence/review
   cannot certify a changed artifact. PM owns Jira, merge, and next-ticket selection.

Routine tests, scoped commits/pushes, PR creation, and review fixes do not need
repeated human confirmation. Return evidence to the PM agent, not a request for
the user to approve each handoff. Escalate only concrete missing decisions,
access, or actions outside existing authorization. Do not claim self-review is
independent. Do not continue polling after the assigned task ends.

Before hand-back, use sstack-mode references/learn.md when the work exposed a
repeatable failure or stale recipe. Return the proven lesson with the evidence.
