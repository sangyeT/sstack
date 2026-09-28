# Kizen platform contract

Use the installed CLI docs rather than freezing API assumptions here. At session
start in the intended environment folder run `kizen upgrade --check`,
`kizen docs show operating`, and `kizen envs list`. Read the nearest AGENTS.md.
Confirm the resolved business/host: explicit profiles or environment variables
can override the folder pin. Never print credentials or copy another environment's
pin just to make a command work.

Use `kizen <group> <command> --help` and `kizen docs show <surface>` for current
syntax/spec shapes. Use CLI reads for discovery rather than ad-hoc HTTP scripts.
Read live definitions before preparing changes; local specs record intent/history.
Prefer portable field references and preserve existing step/trigger identities
and current revisions on updates.

For platform changes, render the actual dry-run and follow the environment's
explicit approval gate before applying. Reuse existing approval for that exact
scope; do not ask again at each covered step. A changed target or materially
changed plan needs renewed review. A preference for automated gates does not
approve unspecified future Kizen writes.

`kizen code test` executes remotely; its code may call `kizen.api`.
`automations start` can trigger writes or external actions. Neither is an offline
check simply because the CLI calls execution confirmation-free. Inspect code,
inputs, effects, and authorization first. The local wrapper runs neither.

Retain exact execution IDs. Inspect an authorized run with
`kizen automations runs view <execution_id> --json` from the confirmed environment.
Raw JSON can contain sensitive data; sanitize evidence. Parent completion may only
mean dispatch: check child runs and business fields for the same record/run.
Never select “latest” as correlation. Timeout means observation is incomplete,
not failure or permission to resubmit. Inspect before retry; do not assume
exactly-once execution, atomicity, or uniqueness without proof.

Verify rendered UI separately from API success. Confirm the actual UI host from
current documentation/environment; API/UI hosts may differ. Test permission
behavior under the intended role; a service-account success or fake API denial
fixture cannot prove end-user isolation.

Use synthetic data for shared evidence. Keep credentials, patient text, and
unredacted logs out of issues/screenshots. Clinical gate, judge, and human review
are separate states. Blank judge is not PASS; completed activity is not approval.
