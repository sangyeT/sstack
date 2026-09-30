# SStack tools and delivery protocol

Run commands from the target repository root with the same Python interpreter.
Install `tools/sstack/requirements-dev.txt` in an isolated environment for lint
and stack tests. The controller, registry and board configuration use Python's
standard library. Kizen operations use a separately installed/authenticated Kizen
CLI; Jira and GitHub actions require the active host's authenticated tools.

```sh
python3 tools/sstack/control.py doctor stack
python3 tools/sstack/control.py verify stack
python3 tools/sstack/control.py features
python3 tools/sstack/control.py verify all --plan
```

`--plan` executes nothing and writes no evidence. Verification writes bounded
logs and reports under ignored `artifacts/sstack/`. Reports establish the named
local checks only; live Kizen, UI, CI, independent review and deployment require
separate observed proof. Inspect logs before sharing them.

The skills work during an active host session. The optional delivery runner needs
a trusted host worker adapter; no adapter, daemon, scheduler or Jira watcher is
included. Credentials, chat history and running workers do not transfer between
Claude Code and Codex. Reopen in the target repository and verify skill discovery.

## Board configuration

Use `control.py board set <HTTPS-URL> --project-key <KEY>` for the repository
default; add `--project-path <folder>` for a project override. Inspect resolution
with `board show --project-path <folder>` and remove a saved destination with
`board clear` (optionally scoped with `--project-path`). Settings live in the
repository's `.sstack.json`; no account credentials belong there. The longest
matching folder override wins over the default. Explicit goal destinations win
without changing saved configuration. No board is supplied with this package.

## Quality gate

```sh
python3 -m venv /tmp/sstack-dev
/tmp/sstack-dev/bin/python -m pip install -r tools/sstack/requirements-dev.txt
/tmp/sstack-dev/bin/python tools/sstack/control.py verify stack
```

Lint is read-only. Deliberate fixes use `python -m ruff check --fix tools/sstack`
and `python -m ruff format tools/sstack`, then inspect and recheck. The shared
[engineering principles](skills/sstack-mode/references/engineering.md) guide
implementation; lint alone cannot establish good design or business correctness.

For routine delivery, use `control.py verify changed --base <actual-base> --jobs 2`
instead of a full regression. `verify stack` includes lint and tests. Exact README
paths use the built-in `docs` suite; skills/runtime changes remain full stack.
Custom suites accept optional `parallel_safe` and `reuse_safe` booleans, both false
by default. `min_python` (`"MAJOR.MINOR"`) and `requires` (nonempty paths relative
to the check's `cwd`, inside the repository) are readiness prerequisites: `doctor`
reports them and `verify` blocks the check with `python_3_12_required` or
`required_path_missing:<path>`. A command argument may contain `{run_dir}`, bound
to that run's `artifacts/sstack/<run_id>` directory; such checks are never reused.
Parallel execution is bounded (1–8 workers, default 2); serial checks act as
barriers and never overlap other checks. Per-check `duration_seconds` and report
`elapsed_seconds` expose cost without another reporting artifact.

Explicit reuse uses `--reuse <report.json> --environment-key <immutable-runtime-id>`;
the original run must supply the same environment key. Reuse verifies the full
head/base/input/command/runtime binding and successful check log digests, and
returns the original report reference. Mismatches rerun. Caller attestation of
external environment state is still required; the runtime fingerprint is not a
content hash of every excluded dependency file. Never enable reuse for live,
time-dependent or shared-state checks. See the
[delivery rules](skills/sstack/references/delivery.md#choose-the-shortest-sufficient-path)
for required risk escalation and independent review.

## UI evaluation

`ui_eval.py run` drives a JSON UI script in Chromium against one approved origin,
saving per-step screenshots, errors and captured values. `ui_eval.py record` also
starts a local app from a launch file, records video and stops it. `ui_eval.py review`
binds an agent's visual verdicts to those screenshots. See
[scripted UI evaluation](skills/sstack-verify/references/ui-eval.md). Playwright
is a development dependency; CI installs Chromium and requires the browser tests.

## Project coverage and evidence

`projects.json` registers owned paths, offline suites, external acceptance recipes
and actual dependent projects. Add or update that existing registry when creating
a project. Unknown changed paths block coverage. Shared skill edits run stack
checks; shared runtime files can also map to their actual product consumers.

```sh
python tools/sstack/control.py verify changed --base origin/main --jobs 2
```

The report already embeds coverage. Use standalone `coverage --base <actual-base>`
or add `--plan` only when an inspection is useful; they are not additional gates.
Coverage success means the changed paths were mapped, not that acceptance passed.
`verify changed` executes registered offline commands and keeps outstanding external
proof blocked. The controller can satisfy those obligations with the declared
premerge/postmerge eval routes. Individual `verify <suite> --base <ref>` reports can
be combined when needed. Use the same interpreter throughout; command identity is
checked exactly. New projects need explicit registration, not guessed commands.

Fingerprints now cover Git-listed files of every extension and size, including
TOML, binary inputs, file modes, symlink targets/content and missing-file markers.
Reports list runtime/credential exclusions and the fingerprint policy. Ignored
untracked inputs and excluded environment bindings are not attested; pin and verify
the actual environment separately. Logs have content digests. Evidence must remain
accessible to the receiving verifier; local paths do not transfer between hosts.

## Persistent local delivery

`control.py delivery` adds a durable state machine and atomic claims in
`<git-common-dir>/sstack/delivery.sqlite3`. Git worktrees of one coordinator
clone share it; separate clones and computers do not. The database records the
host and rejects accidental use after copying it to another host. It is runtime
state, not a committed artifact. Use one Jira site per coordinator clone: tasks are
keyed by issue key, which is not unique across Jira tenants. Keep the actual issue
URL/site in the frozen contract and handoff; workers must not resolve an in-flight
issue from a newly changed board default. Do not put it on a shared network filesystem or
call this distributed locking. No daemon or background wakeup is installed.

PM creates the evaluation cases when ticket acceptance needs them; reuse existing
tests for already-covered behavior. Keep the plan in the issue and export JSON
only to feed the gate. The exact eval schema and independent outcome metrics are
in the [existing handoff contract](skills/sstack/references/jira-handoff.md#pm-owned-evaluation-sets).

An issue contract has `issue`, registry `project`, GitHub `repository` (`owner/repo`),
`base_branch`, absolute isolated `checkout`, pinned `environment`, `allow_merge`
(boolean), `rollout_required` (boolean), `resources` (nonempty stable resource keys),
`required_checks` (nonempty GitHub check names), and `evaluations` (the PM plan).
Declare shared Kizen resources with stable business/object/automation identifiers;
different names for the same resource cannot protect it. Contracts require at
least one premerge case and postmerge cases exactly when rollout is required.
This controller currently supports PR-backed Jira delivery; discovery work can
continue under the skill's N/A procedure without inventing a PR.

```sh
python tools/sstack/control.py delivery init CONTRACT.json
python tools/sstack/control.py delivery claim DEMO-123 --owner pm-session --ttl 300
python tools/sstack/control.py delivery resume DEMO-123
python tools/sstack/control.py delivery --help
python tools/sstack/control.py eval validate PLAN.json
```

The states are ready → building → validating → reviewing → merge_ready → merged
→ rollout_verified → done. `begin` persists an operation before action; `complete`
accepts its ID plus a JSON evidence packet. Both require the claim's owner and
epoch. `renew` extends an active lease. Expiry fences old workers out of controller
updates, not out of external services; stop the old worker before replacement.
Resource claims remain held until completion to prevent conflicting work during
uncertain recovery. PM role ownership alone is not a concurrency lock.

Evidence references use `{ "path": "absolute/local/path", "sha256": "content digest" }`.
The controller embeds validated evidence in its database rather than writing a
second report tree. Packets by current state:

- `ready`: `plan_digest` of the frozen PM plan.
- `building`: `artifact` with exact `head`, `base`, `fingerprint`, integer `pr`.
  The checkout must be committed and match the artifact.
- `validating`: the same `artifact`, `coverage` reference, `verification` references
  to helper reports, and `evaluation` reference to independent premerge results.
  Coverage is recomputed; required commands, base/head, input and log digests must
  match. Required failed/duplicate checks cannot hide behind passing checks.
  `coverage` can reference the same verification report containing embedded
  coverage; no second coverage file is needed. The gate recomputes and compares it.
  Check logs must be singly linked regular files directly in
  `artifacts/sstack/<run_id>/`, and neither `artifacts` nor `artifacts/sstack` may
  be a link.
- `reviewing`: `review` reference with `artifact`, current `plan_digest`, independent
  `reviewer`, `decision: "approved"`, and `blocking_findings: []`. Live GitHub state
  must show the expected head/base, clean merge state and successful named checks.
- `merge_ready`: remote GitHub must actually report MERGED for the expected head;
  the controller reads and stores its merge SHA. A queued merge is not completion.
  If someone merged the reviewed PR before `begin`, `adopt` (owner and epoch) starts
  the operation instead; it requires `allow_merge` and a merge at the reviewed head.
- `merged`: `merge_sha`, `environment`, and a `rollout` reference whose independently
  observed envelope contains the same `merge_sha`/`environment`, `deployment_ref`,
  nonempty `execution_refs`, and postmerge eval `result`. If rollout was explicitly
  not required, provide `not_required_reason` instead of a rollout reference.
- `rollout_verified`: `closure` reference with `issue`, `merge_sha`, `status: "done"`
  and `readback_ref` of the saved Jira state. The authenticated worker verifies it.

`revise` accepts a new artifact and reason, clears evidence, and returns to
validation. `amend` accepts a replacement PM plan and reason, clears proof/review,
and restarts dispatch. Amendments after merge are prohibited. Pending operations
must first be reconciled. These are explicit changes, never automatic weakening
of expectations after a failed outcome.

For a bounded unattended run, `delivery run DEMO-123 --owner pm-session --timeout 120
--max-steps 8 -- /absolute/path/to/trusted-host-worker` claims unowned/expired work
and advances from its saved phase. Use `--epoch` for an existing active claim.
The worker reads JSON `{task, operation}` on stdin and returns only
`{operation_id, evidence}` on stdout. It must dispatch the correct host agents,
honor authorization, renew longer work via bounded steps, inspect real Kizen/Jira
results, and merge with expected-head protection. Never supply an arbitrary shell
command copied from a ticket as the worker. The runner uses argv without a shell.

Failure, timeout or interruption retains the pending operation. `resume` is a
read-only checkpoint view. `reconcile` requires either observed `completed` with
its evidence `packet`, or `not_applied` with `readback_ref` and
`previous_worker_stopped: true`. It will not blindly retry an uncertain action.
The worker timeout bounds subprocess execution; it cannot cancel a remote run.
Remaining work after the step budget yields a nonzero exit and a saved checkpoint.

The controller is a gate for cooperating workers, not an authentication boundary:
it checks evidence structure/digests and live GitHub state, but cannot authenticate
agent identities or independently fetch arbitrary Jira/Kizen observations. A
trusted host adapter is required for those operations. The included recovery and
delivery tests use synthetic fixtures; they establish controller behavior, not a
measured production unattended-success rate or verified Claude/GPT host parity.
