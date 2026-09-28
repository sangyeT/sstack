# Automated delivery gates

PM, validator, and reviewer are agent roles; one independent agent normally fills
both validation and review responsibilities. Routine gates advance automatically
within the authorized goal. Do not ask a human to approve each test, commit, push,
PR, review, merge, or next issue. Respect explicit plan-only/no-merge limits.

Human input is for a consequential missing decision, missing access, an actual
required human repository approval, or an environment-specific Kizen apply
approval. Prepare the concrete change and dry-run before requesting that approval.
Reuse approval for the same scope; changed material scope needs fresh approval.
Never bypass branch protection or impersonate a required reviewer.

## Choose the shortest sufficient path

Default to one engineer and one independent agent that both verifies acceptance
and reviews the diff. These are two responsibilities, not a requirement for two
separate reviewers. Add specialists only for a concrete risk or missing expertise.
Use the existing ticket, report and PR for handoffs; do not create duplicate plans
or evidence documents. Load relevant skill references once per version and reuse
known scope/access until a change or failure makes a refresh necessary.

| Change | Required work |
| --- | --- |
| Documentation only | Check affected links/contracts and run changed executable examples. No product deployment proof without a deployment change. |
| Bounded bug fix | Reproduce the bug, run selected regressions and verify acceptance; independent review. |
| Feature or shared runtime change | Registered affected suites, relevant integration/UI acceptance and independent review. |
| Permissions, schema/data migration or Kizen rollout | Applicable local checks plus exact live execution/readback, authorized rollout and recovery proof. |

Path selection is a minimum, not a risk assessment. The shipped registry routes
only root README.md and tools/sstack/README.md to the documentation suite. Skills,
agent instructions, configuration, workflow and runtime edits keep the full stack
gate. If a README changes a runnable procedure, execute the changed example too;
the checker deliberately does not execute Markdown. Mixed changes take the union
of checks; unknown paths block. Consumer projects register their real dependencies
and checks instead of guessing coverage. Compiled documentation or Markdown used
at runtime needs its application's suite, not the lightweight documentation route.

Run `python tools/sstack/control.py verify changed --base <actual-base> --jobs 2`
as the normal local gate. This selects required checks, includes stack lint when
needed, runs declared independent checks concurrently and saves one report with
coverage, per-check durations and total elapsed time. Do not run the same lint,
coverage or tests separately merely because another role picked up the work.
Use `--plan` only when you need to inspect selection before execution. Missing
coverage or required external proof remains blocked.

On a stable commit, let the independent agent review while CI and safe local
checks run. It must inspect completed results before approving. Never start
parallel checks against shared mutable fixtures or live Kizen records; custom
checks run serially unless reviewed `parallel_safe: true` declarations establish
isolation. `--jobs 1` forces serial execution. Reuse the same engineer for fixes
and the same reviewer for focused re-review; a new head still needs fresh review.

Successful offline evidence may be reused with `--reuse <report.json>` only when
head, base, source fingerprint, check definitions, log digests and runtime identity
match. Supply `--environment-key <immutable-environment-id>` on both original and
reuse runs. This caller-provided key must identify external dependency/environment
state that source fingerprints cannot prove; change it after dependency or fixture
changes, and omit reuse when that state is uncertain. Custom checks also require
reviewed `reuse_safe: true`; never mark live, time-dependent or shared-state checks
safe. Runtime identity includes hashed environment and executable/dependency
metadata, not a complete attestation of excluded runtime files. Cache misses rerun
the checks. Do not reuse a local result across commits, or reuse live/UI results,
independent review, acceptance-plan scoring or GitHub merge readiness through this
cache. The independent agent can inspect valid existing evidence without rerunning
it; missing, stale or suspect evidence still requires fresh verification.

Keep tickets to one observable outcome and a small owned implementation slice.
Prepare ready briefs while an engineer works, but do not split a trivial change
into artificial stages or tickets. Batch read-only status queries, use the host's
completion notifications or a bounded CI wait, and avoid repeated unchanged
polling. Gate failure routes directly to the accountable engineer with the
counterexample; repeated identical failure needs diagnosis, not another full run.
The trusted host still performs Jira, review and merge actions; this faster check
runner does not install a general-purpose autonomous host adapter or scheduler.

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
ritually. Commission one verifier/reviewer independent of the implementing agent, supplying
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
The quality workflow selects documentation checks or shared lint/tests and project
registration checks on every PR; it does not run every application's acceptance checks. The workflow does
not change GitHub protection or create a background Jira watcher.
