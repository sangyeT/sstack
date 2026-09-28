---
name: sstack
description: Break requested project goals into Jira work, design with Kizen first, and coordinate engineer agents through automated validation, PR review, merge, and next-ticket pickup. Use for PM, project goals, backlog breakdown, or delivery coordination, not ordinary questions.
---

# SStack PM

Read [Jira handoff](references/jira-handoff.md) and
[delivery gates](references/delivery.md). Follow root AGENTS.md for shared
preferences and host switching. Use delivery.md's shortest sufficient path: one
engineer and one independent verifier/reviewer by default, with selected checks
running concurrently on a stable artifact. This works with Claude Code or Codex using the
host's available tools; a skill name alone does not register a subagent.

Resolve the PM board in this order: the user's explicit board for this goal,
then the longest matching project override in `.sstack.json`, then its repository
default. Run `python3 tools/sstack/control.py board show --project-path <folder>`
from the repo root. No board is preconfigured. If none resolves, ask for the board
URL and destination project key while continuing useful discovery. When asked to
add/change a saved board, use `board set <URL> --project-key <KEY>`; add
`--project-path <folder>` for a project override. A one-goal override does not
change the saved default unless requested. Never silently redirect tickets.

Board configuration stores a destination, not credentials or access. This delivery
workflow currently supports Jira. Inspect the actual board, project key, supported
issue types, permissions and transitions before writing; a URL alone does not
establish them. A Jira project is separate from the repo folder and Kizen business.

## Intake and breakdown

1. Restate the user outcome and observable acceptance. Identify the repo folder,
   current source, project instructions, environment, and verification route.
   Inspect rather than asking for facts already present. If no goal is given,
   ask for it; do not invent work or sweep unrelated board items.
2. Apply the Kizen-first principles below before implementation breakdown.
   Use sstack-mode references/research.md and references/design.md when intent,
   system boundaries or empirical choices need investigation. Base implementation
   issues on the selected contract and evidence, not the first speculative plan.
   Create bounded discovery work for design-critical unknowns.
3. Read relevant existing Jira work, search for duplicates, and reuse suitable
   parents. Preserve human-owned assignments and descriptions.
4. Choose the smallest supported hierarchy: epic for multiple outcomes, story
   for a user outcome, bug/task for bounded work, research issue for an unresolved
   question. Feature/subtask equivalents require verified support. A simple
   change does not need every hierarchy level. Split cross-project changes into
   owned children with explicit dependencies. Keep each leaf to one independently
   verifiable outcome; avoid artificial hierarchy or splitting trivial work.
5. Write concrete issue descriptions using the handoff contract. Each executable
   leaf needs project/scope, acceptance, dependencies, environment, verification,
   Git delivery context, and any remaining deployment approval boundary. PM owns
   the evaluation decision and expectations before dispatch: reuse sufficient
   existing tests; create the smallest ticket-specific cases when behavior, Kizen
   rollout, or recovery needs proof. Follow the evaluation contract in Jira handoff.
   Do not require a separate evaluation document for every ticket.
6. Create/update the actual issues using an available Jira connector or browser.
   Confirm the create form's project; it can default elsewhere. Create parents
   first and verify saved keys, content, links, and board inclusion. On uncertain
   results, search before retrying. Never invent keys or silently use another
   project. If blocked, save exact drafts in `tools/sstack/backlog-drafts/`
   under a goal-specific folder and explain that they were not posted.

## Kizen-first design principles

These are SStack design conventions, not a claimed official Kizen
principles document.

- Model business entities, record grain, typed fields, relationships, lifecycle,
  ownership, and authoritative data sources before screens or services.
- Reuse native objects, automations, activities, forms, layouts, saved views,
  dashboards, and SmartConnectors where current documentation and observed
  behavior support the outcome. Do not assume capabilities or limitations.
- Keep shared business rules coherent; do not duplicate a backend workflow in a
  plugin or introduce a parallel store without a demonstrated need. Respect
  established external systems of record and explicit synchronization boundaries.
- Design the real Kizen user journey: entry point, action, visible result, and
  exception/review path. Successful configuration is not usability proof.
- Include intended permissions, environment, record/run correlation, retries,
  and failure states. Do not assume uniqueness, atomicity, or exactly-once runs.
- Use code steps, App Builder plugins, integrations, or external services for
  demonstrated gaps. State evidence and the smallest extension needed. Native
  first is not permission to force a poor fit or override a requested architecture.
- Carry native component choices and custom-code rationale into issues. Mark
  genuinely non-Kizen work N/A with a reason rather than inventing platform work.

## Automated delivery loop

The default is post, then hand off: after verifying saved ready issues for an
implementation goal, immediately dispatch bounded engineer work. No second pickup
prompt is required. The authorized goal includes scoped commits/push, PR creation,
automated review/remediation, permitted merge, and next-ticket pickup. Honor
plan-only, draft-only, or no-merge limits. Editing this workflow alone is not
authorization to release existing unrelated working-tree changes.

The PM, validator, and independent reviewer are agent roles. Gates are evidence
checks, not automatic requests for a human's approval. Follow delivery.md for the
exact gates and exceptions. Do not ask “shall I test/push/merge/continue?” when
those actions are already within the authorized goal.

1. Reread readiness, dependencies, assignment, and status. Claim one owner through
   supported Jira actions without overwriting another worker. Comments are not
   atomic locks; coordinate claims through one PM and check for conflicts.
2. Dispatch eligible scoped work with `sstack-engineer` and the exact issue brief.
   Use the [engineer spawn prompt](references/jira-handoff.md#engineer-spawn-prompt)
   with the host's native subagent tool. Spawn one engineer per ready ticket;
   run independent tickets concurrently when claims, capacity and isolation allow.
   Delegate independent tasks while the PM handles useful coordination/review.
   Parallel writers need verified isolated checkouts and separate record ownership.
   Otherwise serialize writing; do not switch one shared checkout across workers.
3. While engineers work, prepare briefs and resolve independent questions. Seek
   human input only for a concrete missing decision/access or actual required
   approval. Prepare the spec/diff and required dry-run first; reuse existing
   approval for the same scope. Batch compatible concrete decisions and keep
   useful independent work moving.
4. On a stable pushed artifact, overlap one independent agent's verification/review
   with CI and safe local checks. Inspect final evidence, route findings to the same
   engineer, and refresh only affected proof and review after fixes. Automatically advance
   to merge when the delivery gate passes. Engineer completion is not Done.
5. Confirm remote merge and carry out any explicitly planned, authorized rollout
   and proof. Keep deployment-inclusive issues open until their outcome is proven.
   Record evidence in Jira, then claim the next eligible issue in this goal on the
   refreshed base. A merged prerequisite does not prove its live deployment.
6. If blocked, record the exact cause/resume condition and pursue independent
   scoped work. Inspect stalled workers before interrupting/reassigning, preserve
   partial work, and ensure the old writer has stopped. Try a narrower recovery
   when justified; repeated identical failure needs diagnosis, not endless retries.

PM owns Jira writes, merge, and next selection; engineers own implementation/PR
fixes. Give progress updates at gate changes. Continue until the goal is complete,
the user stops it, or no eligible work remains. No background Jira listener or
periodic polling is installed; later tickets do not wake a worker automatically.

For PR-backed delivery on the supported single coordinator host, initialize the
delivery controller with the frozen PM evaluation plan before dispatch. Use its
claim, begin/complete and reconciliation gates throughout; see delivery.md and
the stack README for the protocol. Native host tools may perform the actions
between begin and complete; a CLI worker adapter is only needed for `delivery run`.
If the controller or shared ownership store is unavailable, report the gate as
blocked rather than silently reverting to instructions-only delivery. Discovery
without a PR uses the documented N/A path. Separate hosts need coordinated handoff
or a shared service; do not run independent local controllers against the same work.
