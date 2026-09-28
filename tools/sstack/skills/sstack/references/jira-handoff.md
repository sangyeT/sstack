# Jira handoff contract

Resolve the destination using the PM skill's board precedence and
`control.py board show --project-path <folder>`. There is no built-in board.
Inspect supported issue types, fields, permissions, and transitions each session.
Never silently redirect work to another Jira project. Resolve and retain the actual
issue URL/site at creation. Saved board changes apply to future goals, never to
in-flight tickets. The local controller keys tasks by issue key, so use one Jira
site per coordinator clone; separate sites need separate coordinators even when
project keys match. Workers must use the ticket's pinned destination for updates.

## Executable issue template

```markdown
## Outcome
Who needs what observable result, and why?
## Project and ownership
Saved issue URL and Jira site/project/board; freeze these for this ticket.
Repo-relative project directory; owned files/components; exclusions; worker owner.
Applicable AGENTS.md/CLAUDE.md and canonical engineer skill.
## Context and design
Verified facts, sources, assumptions, and unresolved questions.
Kizen entities/relationships/workflows/permissions/user surfaces to reuse.
Custom code rationale and authoritative data source; or Kizen N/A with reason.
## Environment
Pinned environment/business/host or explicit N/A; no credentials or patient data.
## Scope
Included changes and explicit exclusions.
## Acceptance and evidence
Observable criteria with exact local/live/UI verification routes.
For each criterion: premerge or explicitly planned postmerge, required evidence,
and owner. Declare this timing before implementation; do not defer failed gates.
PM evaluation decision: reuse named checks with coverage rationale, or define
ticket-specific cases, expected outcomes, and frozen plan digest before dispatch.
## Dependencies
Actual saved parent/issue keys; prerequisite outcomes, including required rollout.
## Execution and delivery
Git remote/base, branch/checkout ownership, dirty-file exclusions.
Deployment effects of merge, approval already granted, specific remaining boundary.
Required checks, independent review, merge policy, and rollout/readback route.
## Completion packet
PR URL, tested head SHA, evidence/results, reviewer decision, CI state,
confirmed merge SHA, rollout proof or pending state, remaining blockers/next action.
```

Use supported hierarchy fields to link parents and dependencies; text alone may
not establish Jira relationships. Do not fabricate estimates or assign people
without evidence. Shared evidence must be accessible to the receiving worker:
local paths need an artifact transfer or shared link. Redact sensitive data.

Ready means outcome, scope, environment, criteria, verification, dependencies,
design, and delivery context are concrete enough to execute. A board column alone
does not establish readiness. Discovery can be ready with a bounded question and
evidence deliverable. PM coordinates claims; Jira comments are not atomic locks.

After creation, read back the saved key, project, description, relationships, and
board visibility. Search before retrying an uncertain write. Keep exact drafts in
`tools/sstack/backlog-drafts/<goal>/` if posting is blocked and label them
unposted. Do not represent draft text as a live ticket.

## Engineer spawn prompt

PM uses the active host's native subagent tool, not a new user-visible chat, for
ticket execution. A skill name is not a registered agent type: give a supported
worker the canonical engineer skill path and the filled brief below. Replace every
placeholder before dispatch; pass the actual issue snapshot when the worker lacks
Jira access. Do not assume inherited chat history or credentials.

Spawn one accountable engineer per ready ticket. Parallelize only tickets whose
dependencies are satisfied, with distinct branches/worktrees, owned paths and
nonconflicting Kizen resources. Acquire controller claims before dispatch and
respect the host's actual worker capacity, preserving capacity for independent
verification/review. Queue the remainder. Never spawn duplicate owners to speed up
one ticket. A single ticket can delegate bounded read-only research/tests; extra
writers need PM-assigned isolated ownership first. No fixed agent count is required.

Use this prompt, attaching the existing ticket/eval record rather than creating a
separate handoff document:

```text
Implement <issue key> only, as engineer <worker identity>.
Read <absolute checkout>/AGENTS.md, applicable project instructions, and
<absolute checkout>/tools/sstack/skills/sstack-engineer/SKILL.md.

Outcome and current issue snapshot: <verified brief or accessible issue record>.
Project: <folder>. Work only in <absolute isolated checkout>, branch <branch>.
Git remote/base and current base SHA: <values>.
Owned paths and Kizen resources: <explicit ownership>; exclusions: <paths/resources>.
Dependencies already satisfied: <verified outcomes>.
Environment/business/host and authorized actions: <bindings and exact scope>.
Controller: <coordinator checkout>, issue <key>, owner <claim owner>, epoch <epoch>,
operation <ID>. PM retains coordination; stop on ownership loss or scope conflict.
Acceptance and evaluation plan: <existing record/reference and frozen digest>.
Delivery path and risk: <docs/bug/feature/live; reason and additional gates>.
Existing proof: <report references and unchanged bindings, or missing evidence>.
Verification: <exact commands/interpreter, premerge/postmerge cases, live/UI routes>.

Implement, run applicable checks, commit/push only owned changes, and open/update
the scoped PR. Preserve expected outcomes; report a requirement mismatch to PM.
Return actual base/head SHAs, PR URL, observed case results, evidence references,
remaining rollout requirements and blockers. Do not merge or mark Jira Done.
Report progress/blockers to PM; stop after hand-back until assigned review fixes.
```

Record the returned native worker ID against the ticket's declared engineer
identity in the existing checkpoint. PM keeps leases current, watches worker
outcomes, and sends review fixes to the same worker. Before replacing a worker,
stop it and reconcile its pending operation; do not launch a competing replacement.
Once the engineer supplies a stable head, use one different worker for both
independent verification and review, overlapping with CI/local checks, with
the requirements, frozen plan and actual diff/results. PM advances controller
gates, merges when eligible, verifies rollout, updates Jira, and dispatches the
next ready ticket in the same authorized goal. If native delegation is unavailable,
report it; sequential implementation does not count as independent review.

## PM-owned evaluation sets

PM defines the expected business outcome from acceptance before implementation.
Reuse existing tests and feature recipes when they cover the criteria; a route to
an existing test is a valid case. Create additional cases only for missing proof,
especially new behavior, Kizen writes, retries, permissions or recovery. A small
documentation-only change can reuse contract checks with a recorded rationale.
Keep the decision and cases in the existing issue/verification record. Export
JSON only when needed by the executable gate; do not create a parallel eval report.

Use `python3 tools/sstack/evaluations.py validate PLAN.json` to validate and
freeze a plan digest. The schema is version 1 with exactly these fields:

```json
{
  "schema_version": 1,
  "issue": "DEMO-123",
  "author": "pm-session-id",
  "implementer": "engineer-session-id",
  "acceptance_ids": ["AC1"],
  "cases": [{
    "id": "valid-input",
    "acceptance_id": "AC1",
    "input": {"quantity": 2},
    "expected": {"total": 10},
    "phase": "premerge",
    "surface": "local",
    "route": "existing test or concrete verification recipe"
  }]
}
```

All acceptance IDs need coverage. Use premerge/postmerge phases and local/live/ui
surfaces. Route descriptions are references, never executable code supplied to
the scorer. Freeze expectations at dispatch. A legitimate requirement amendment
needs PM rationale and independent review, a new digest, and renewed evidence;
do not change expectations or postpone failed cases to bless an implementation.

An independent verifier records schema_version, issue, plan_digest, head, base,
fingerprint, phase, verifier, and cases. Each result case has exactly id,
observed (actual JSON business values), and evidence (nonempty reference strings).
Score with `evaluations.py score PLAN.json RESULT.json --head SHA --base SHA
--fingerprint DIGEST --phase premerge` using controller-observed bindings. A
changed plan, missing case, wrong result, stale binding or self-verification cannot
pass. A phase without cases is not_required, not a behavioral pass. Postmerge
checks must still run before deployment-inclusive completion.

The scorer compares supplied values; it does not fetch references or authenticate
identities. The verifier must inspect actual logs, records and UI evidence, with
fresh execution/deployment correlation. A screenshot and configuration file alone
cannot establish behavior. Keep sensitive record contents outside shared evidence.

Retain a small baseline of interruption, ownership, stale-evidence and recovery
cases for the stack. Add cases for an affected ticket before its run and turn
observed defects into reusable regressions between runs. Dynamic coverage must
not silently change the answer during a run.

For end-to-end evaluation, an independent auditor records actual outcome checks,
not the engineer's verdict. `evaluations.py metrics AUDITS.json` accepts a list of
records with issue, implementer, auditor, claimed_done, outcome_correct,
recovery_required, recovered (boolean when required, otherwise null), and
unnecessary_interventions (nonnegative count). It reports observed counts and
rates with denominators; empty samples produce null rates. These are supplied
audits, not automatic measurements of live unattended delivery.
