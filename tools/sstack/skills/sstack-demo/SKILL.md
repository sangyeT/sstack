---
name: sstack-demo
description: Build a presentable demo quickly from an agreed script, with scripted self-checks and an honest faked list. Use for demos, walkthroughs, and stakeholder previews, not for tickets, PRs, or delivery.
---

# SStack demo

A demo shows an agreed story reliably and honestly. It is not delivery: skip Jira,
the delivery controller, frozen eval plans, independent code review, CI and merge.
Delivery requests go to `sstack`; do not load its delivery or Jira references here.
Root AGENTS.md secret, customer-data and approval rules still apply.

## Boundaries

- Demo code lives under `demos/<name>/` or on a `demo/<name>` branch, never merges
  to the default branch, and never counts as completion evidence for a ticket.
- Use synthetic data only. Kizen writes go only to a demo sandbox business whose
  standing write scope the user has granted for demo-tagged records. Without that
  sandbox, fake the step or ask for access; never write to another environment.
- Mocks, stubs and hardcoded responses are allowed when listed as faked.
- Never present a step as real without proof that it ran against the real system.

## 1. Script before building

Write `demos/<name>/script.md` with the audience, time budget, and 3–7 steps:

```markdown
| # | Action | Visible result | Real or faked | Proof or fake detail |
| --- | --- | --- | --- | --- |
| 1 | Enter $6,000 stocks and $4,000 bonds | Chart shows 60% / 40% | Real | Sandbox record readback |
| 2 | Refresh prices | Prices update | Faked | Hardcoded price fixture |
```

Confirm the script with the requester when intent is unclear; otherwise start.
Script changes from stakeholder feedback are expected, not violations.

## 2. Build and self-check

Reuse existing app code, templates and seed data before writing new ones. Start
the app from a clean reset, drive each step with a browser tool, check the visible
result, and record the run or save a screenshot per step. Treat console errors,
failed requests and blank states on the path as failures. Fix and rerun until
every step passes. Skip unit coverage and code review; this run is the gate.

## 3. Honesty check

- Each real step has evidence it ran: for Kizen, read back the record it wrote in
  the sandbox. A step without proof is relabeled faked.
- Every mock, stub or hardcoded response in `demos/<name>/` appears in the faked
  column, and every faked entry exists in the code.
- No real customer data, credentials or non-sandbox writes.

## 4. Rehearse

Run the full script twice from a clean reset within the time budget. Both runs must
pass. For a customer-facing demo, optionally ask a fresh agent to review only the
recording and script: does it tell the story, and what would confuse the audience?

Report the URL or launch command, recording or screenshots, rehearsal results and
the faked list. Stakeholder feedback returns to step 1.

## 5. Promote or archive

When a stakeholder approves, hand off to `sstack` to promote the demo into tickets:

- Real steps become acceptance criteria. Their inputs and visible results become
  the ticket's frozen eval cases (`surface` `ui` or `live`, as observed).
- Each faked step becomes scope: its own ticket or explicit work in a story.
- Link the script and recording as the agreed user journey and design.
- The engineer builds to delivery standards and may borrow demo code; the demo
  branch itself does not merge.

A rejected demo is archived with its script and recording; nothing enters Jira.

## Register demos in a consuming project

Unknown paths block `control.py verify changed`, so register the demo folder with
its own project entry in `tools/sstack/projects.json` instead of product suites.
The scripted run is external proof, so name this skill as the recipe; coverage
then reports it as `external_acceptance_not_run` rather than passed.

```json
{"id": "demos", "paths": ["demos/"], "suites": [],
 "external": ["tools/sstack/skills/sstack-demo/SKILL.md"], "affects": []}
```
