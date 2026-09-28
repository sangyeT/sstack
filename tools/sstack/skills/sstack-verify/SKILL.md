---
name: sstack-verify
description: Verify project behavior and maintain project feature recipes, separating local tests, live record readback, and rendered UI evidence. Use for acceptance checks, proof requests, or verification-map drift.
---

# Verify solutions

Read [features](references/features.md) for the affected journey and
[platform](references/platform.md) before Kizen interaction. Commands below run
from the repository root; the wrapper itself works from any working directory.

Normally one agent performs both independent acceptance verification and PR
review. Inspect valid existing evidence before deciding to rerun checks. Follow
[delivery efficiency rules](../sstack/references/delivery.md#choose-the-shortest-sufficient-path)
for check selection, safe parallel work and reuse; self-review is not independent.

For stack checks, first install the pinned development dependencies into an
isolated environment as described in ../../README.md, and use that interpreter.

```sh
python3 tools/sstack/control.py verify changed --base <actual-base> --jobs 2
```

Use `doctor <suite>` only when prerequisites are uncertain, `features` to locate
recipes, and `verify changed --base <actual-base> --plan` to inspect selection
without running it. Standalone `coverage --base <actual-base>` is optional; the
normal verification report already embeds coverage. Do not run all of these in
sequence for every handoff.

`verify all` runs each existing offline check independently. Failure, missing
tools, and timeout never pass. Separate logs and report.json survive under
`artifacts/sstack/<run>/`. Reports record git revision and a local source
fingerprint because the checkout may be dirty. These checks never authenticate
to Kizen, start its workflows, call an LLM, or prove UI correctness. A wrapper
around existing suites does not establish their completeness.

Reproduce the actual user input/action. Assert observable values/writes/no-writes
for pure logic. For platform work inspect current state, exact execution and child
runs, and the corresponding persisted business result. For UI work drive the
documented user path with available browser tools and inspect rendered output.
Capture the trigger and outcome, not just a final screen. Use synthetic records.

Separate local, live Kizen, UI, and untested paths. A build is not live proof;
engine completion is not business success. Inspect structured errors/per-operation
statuses even when the CLI exits zero. Zero tests is not behavioral verification.
For PRs bind evidence to the tested commit/artifact; changes, conflict resolution,
or base integration require checks of affected behavior and refreshed review.

Start only the documented relevant server after prerequisites pass, using the
affected project's launch command; record the actual URL and process. Stop only processes started
for this verification. Hosted Kizen UI has no local teardown. Do not reset shared
fixtures, cancel other runs, or remove evidence as automatic cleanup.

Finish with the proven result, evidence, and concrete gaps. Update feature-map
paths after verified changes. If blocked, name the exact failed command and missing
prerequisite; never substitute a mock screenshot or invented pass.

## Ticket evaluations

Read the PM evaluation decision and frozen plan in the issue's
[Jira handoff contract](../sstack/references/jira-handoff.md). Independently
inspect every required case for this phase, capture actual business values and
accessible evidence references, then score against the frozen expectations.
Use the controller's current head/base/fingerprint and plan digest. Do not replace
observations with a passed flag, defer failed cases, or edit expected outcomes to
match implementation. Live and UI observations need actual run/record/rendered
proof; the JSON scorer cannot establish their authenticity. Keep pending
postmerge cases visible. Reuse existing records instead of duplicating reports.

## Maintain and extend coverage

Use [maintenance](references/maintenance.md) to audit affected recipes and repair
proven drift. The [project index](references/features.md) explains how to locate each project's
registered checks and recipes; confirm they exist on the current branch.
Before introducing a new recipe, demonstrate one complete launch/health/action/
result/evidence/cleanup cycle on its real surface. Until then label it source-only.
