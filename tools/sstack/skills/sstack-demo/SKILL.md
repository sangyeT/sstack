---
name: sstack-demo
description: Build a presentable demo quickly from an agreed script, with scripted self-checks and an honest faked list. Use for demos and stakeholder previews, not for tickets, PRs, delivery, or technical prototypes.
---

# SStack demo

A demo presents an agreed story to an audience reliably and honestly. It is not
delivery: skip Jira, the delivery controller, frozen eval plans, independent code
review, `verify changed`, CI and merge; this loop's checks replace them. Delivery
requests go to `sstack`; do not load its delivery or Jira references here. To
settle a technical uncertainty, use the `sstack-mode` Prototype workflow instead.
Root AGENTS.md secret, customer-data and approval rules still apply.

## Boundaries

- Work on a `demo/<name>` branch with the script and assets under `demos/<name>/`.
  The branch never merges and is never completion evidence for a ticket.
- Faked steps are labeled disposable prototypes under engineering rule 1 in
  [engineering principles](../sstack-mode/references/engineering.md).
- Use synthetic data only. Read
  [platform](../sstack-verify/references/platform.md) before live Kizen
  interaction. Record writes go only to a sandbox the user approved for this demo;
  any Kizen configuration change follows platform.md's dry-run and approval rules.
  Without an approved sandbox, fake the step or ask for access.
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

Reuse existing app code, templates and seed data before writing new ones. Start from
a clean app state with a fresh run marker; leave earlier sandbox records in place
rather than deleting them. Encode the script as a
[UI script](../sstack-verify/references/ui-eval.md) and run `ui_eval.py run`
against the approved origin; add `--video` for a recording. It checks each step,
saves a screenshot per step, and fails on console errors or failed requests.

Then do the visual check: view every screenshot, with computer use or by opening
the image, against the script's visible result and record verdicts with
`ui_eval.py review`. Fix and rerun until the review passes.

## 3. Honesty check

- Each real step has evidence it ran: for Kizen, read back the record it wrote,
  matched by a marker unique to this run. A step without proof is relabeled faked.
- Every mock, stub or hardcoded response in the branch's diff from the default
  branch appears in the faked column, and every faked entry exists in the code.
- No real customer data, credentials or unapproved writes.

## 4. Rehearse

Run `ui_eval.py run` twice more with fresh markers within the time budget. Both
runs must pass automated checks and visual review. For a customer-facing demo, optionally ask a fresh agent to review only the
recording and script: does it tell the story, and what would confuse the audience?

Report the branch, URL or launch command, recording or screenshots, rehearsal
results and the faked list. Stakeholder feedback returns to step 1.

## 5. Promote or archive

When a stakeholder approves, hand off to `sstack` to promote the demo into tickets:

- Each real step becomes an acceptance ID with an eval case: its input, expected
  business values (for example `{"stocks_pct": 60}`, not the displayed text),
  phase `premerge` or `postmerge`, and surface `local`, `live` or `ui` for the
  proof delivery will collect.
- Each faked step becomes scope with its own acceptance criteria and eval cases.
- Link the script and recording as the agreed user journey. They are references,
  not result evidence; design still follows the `sstack` Kizen-first principles.
- The engineer builds to delivery standards and may borrow demo code, but must
  replace every faked-list item with a real path.

Archive a rejected demo by pushing its branch unchanged, so the script and
recording links stay valid. Nothing enters Jira.
