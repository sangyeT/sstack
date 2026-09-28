# Automated delivery gates

PM, validator, and reviewer are agent roles. Routine gates advance automatically
within the authorized goal. Do not ask a human to approve each test, commit, push,
PR, review, merge, or next issue. Respect explicit plan-only/no-merge limits.

Human input is for a consequential missing decision, missing access, an actual
required human repository approval, or an environment-specific Kizen apply
approval. Prepare the concrete change and dry-run before requesting that approval.
Reuse approval for the same scope; changed material scope needs fresh approval.
Never bypass branch protection or impersonate a required reviewer.

## 1. Dispatch

Read current Jira and Git state. Resolve the real remote and base (do not assume
`main`). Give one engineer an owned checkout/branch, normally `codex/<issue>-<slug>`,
exact issue brief, instructions, dirty-file exclusions, and verification commands.
Parallel writers need isolated checkouts and nonconflicting live record ownership.
Before resuming elsewhere, reconcile prior workers and transfer actual code.

Declare acceptance timing in the original brief. Premerge checks must pass before
merge. Explicit postmerge rollout criteria can remain pending at merge, but keep
the ticket open. A failing premerge criterion cannot be relabeled after the fact.
Inspect whether merge itself deploys; it must not trigger an unapproved mutation.

## 2. Engineer implementation and validation

Read applicable project instructions and Kizen docs. Implement the scoped change,
then run meaningful relevant checks. Report each criterion as passed, failed,
blocked, not run, or N/A with reason. Zero discovered tests do not prove success.
Separate local tests, live Kizen readback, and real UI proof. Never infer deployed
behavior from local fixtures or configuration writes.

Use scoped staging and inspect the staged diff. Never `git add .` in a shared dirty
tree. Commit/push owned changes and create a PR with issue link, intended behavior,
validation and remaining planned rollout. Use a body file for multiline CLI text.
Search for an existing PR before retrying uncertain creation. Draft PRs are fine
for early visibility but do not satisfy readiness. Record the tested commit SHA.

## 3. Validate and review

PM inspects the actual artifact, diff, and acceptance evidence. Rerun checks when
evidence is missing, stale, or a concern justifies it; do not repeat everything
ritually. Commission a reviewer independent of the implementing agent, supplying
requirements and raw base/head diff rather than a request to rubber-stamp it.
If independent delegation is unavailable, say so; self-review is not independent.

Send actionable findings to the engineer, then validate fixes. A changed head
invalidates review of the previous head: refresh affected tests and review the new
head. Check integration with the current base. Distinguish code defects, missing
evidence, and consequential product decisions. Only the last needs user input.

## 4. Merge gate

PM checks fresh remote state: correct PR/base and expected head, all required
premerge acceptance, independent review, current required CI and branch/queue
policies, no unresolved blocking findings. Skipped/missing required checks are not
passes. If CI is absent, document that fact and use the declared local proof;
do not claim CI ran or bypass a policy requiring it.

Merge with a supported repository method and expected-head protection where
available. No admin override or force-push to evade gates. Enqueued or auto-merge
enabled is not merged: read back the actual merged state and merge commit.

## 5. Outcome, Jira, and next issue

Run authorized planned rollout and readback/UI checks after confirmed merge.
Kizen apply operations still follow project dry-run and explicit approval rules.
Deployment failure or missing required proof keeps the issue open and dependent
work blocked. Merge alone does not establish a live outcome. Non-code discovery
or configuration work can mark PR/merge N/A with a reason, not invent a PR.

PM records proof and transitions Jira only when the issue's required outcome is
met. Reconcile failed Jira updates before releasing dependent work. Then refresh
the base and pick the next ready issue in this authorized goal, by dependency and
priority. Continue independent eligible work while a specific item is blocked.
Do not sweep unrelated board work or launch duplicate workers.

## Durable checkpoint

The executable local controller is `python3 tools/sstack/control.py delivery`.
See the existing [README](../../../README.md#persistent-local-delivery) for its
contract, worker protocol and recovery commands. Initialize one issue contract
with the frozen PM eval plan before dispatch; acquire the ticket/resource claim
and pass its owner, epoch and operation ID through each worker handoff.

Use `begin` before actions and `complete` with the matching operation and evidence
afterward. `resume` shows persisted state. `run` advances through an explicitly
configured host worker command; it does not invent an agent command or credentials.
Uncertain operations remain pending, including after worker failure or timeout.
Reconcile observed completion, or confirm no action applied and the old worker
stopped before retrying. Revisions clear old proof; PM eval amendments require a
reason, reset dispatch and invalidate the old review. Never update the SQLite rows
directly to bypass a gate.

The controller checks local ownership, current source/coverage, report digests,
registered offline commands, case results and independent review declarations.
It reads current GitHub head/base/CI before merge dispatch and confirms the actual
merge afterward. Workers must use expected-head protection for the mutation and
respect repository/environment policies; a preflight is not a transaction with
GitHub. Kizen and Jira evidence comes from the authenticated host adapter/verifier.
Its identity and truthfulness are not authenticated by this local state machine.

Use one coordinator clone on one host. Its worktrees share a database; unrelated
clones/computers do not. Resource claims survive an expired lease until the ticket
is recovered/completed. Stop old workers before transfer. A local lease cannot
revoke external credentials or cancel an already-submitted platform operation.
No scheduler, production host adapter or cross-machine lock service is installed.

At each handoff save: issue, owner, phase, checkout/branch, dirty-file exclusions,
remote/base/head, PR URL, criterion results and evidence SHA, CI/review decision,
merge SHA, deployment status, blockers/resume conditions, and next action.
This permits Claude/Codex handoff without depending on hidden chat history.

For changes to shared SStack tools/skills, require the SStack quality
workflow (lint and tests) on the current PR head before merge. Project-specific
acceptance remains separate.

These procedures run during active agent work or an explicitly launched worker.
The quality workflow runs shared lint/tests and project registration checks on
every PR; it does not run every application's acceptance checks. The workflow does
not change GitHub protection or create a background Jira watcher.
