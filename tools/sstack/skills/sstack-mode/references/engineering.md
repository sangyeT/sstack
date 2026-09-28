# Make the short route a sound route

Optimize time to a verified outcome, including review and maintenance, rather than
lines produced or time to the first demo. Apply these decisions in engineering and
review; they are judgment rules, not claims that a linter can prove good design.

1. **Smallest complete slice.** Build one real user path through the actual
   boundaries before widening scope. A fake success response, disconnected UI,
   TODO body, or bypassed permission check is not a finished slice. A deliberately
   disposable prototype is fine when labeled and kept out of completion evidence.
2. **Reuse before invention.** Inspect existing code and native Kizen components
   before adding a dependency, custom service or parallel data store. Choose the
   smallest solution that meets the demonstrated need, not a generic framework
   for hypothetical future needs. Remove obsolete paths when replacing them.
3. **Shape the data first.** Name the owner, lifecycle, interface and failure states
   before adding branches. Validate untrusted inputs at boundaries. Do not spread
   duplicate validators or business rules through every layer. Document whether
   retries can repeat a side effect; do not assume exactly-once execution.
4. **Use evidence to choose.** Timebox a small experiment when a technical choice
   is uncertain. Compare actual behavior against a declared criterion. Research
   the fact instead of asking the user to guess; ask for genuine product choices.
5. **Fix the cause, preserve the signal.** Reproduce defects and add an appropriate
   regression. Do not catch everything and return success, hide failed checks,
   weaken assertions, or replace a required real-system check with a mock merely
   to get green. An accepted contract change needs its rationale recorded first.
6. **Make repetition cheap.** After a manual procedure repeats or causes a defect,
   encode the useful part in a command, schema or check. Keep one canonical source
   instead of copying steps across agents. A one-off task need not gain a framework.
7. **Finish the evidence with the code.** Run scoped lint, relevant behavioral tests
   and required live/UI checks. Preserve blocked/not-run states. Record the tested
   artifact and limitations; never equate lint success with product correctness.
8. **Let the code explain itself.** Remove redundant or outdated comments and
   commented-out code in the code you change. Prefer clear names and small functions
   over comments narrating what the code does. Keep concise comments only when
   they explain a non-obvious reason, constraint or workaround; preserve required
   license notices and functional tool directives.

During review, look for unnecessary new layers, duplicated truth, magic fallback
success, unnecessary comments, and missing tests of changed outcomes. Give the
engineer a concrete counterexample or simplification, not a vague demand to use
best practices.

## Executable checks

From the repo root, install `tools/sstack/requirements-dev.txt` into an
isolated Python environment, then run `python tools/sstack/lint.py` with that
interpreter. CI runs the same command and the stack tests. Ruff catches undefined
and unused names, invalid syntax, common bug patterns (including mutable defaults),
broad exception catches, import ordering and obsolete noqa suppressions. Its
formatter removes style debates. The contract checker validates skill metadata,
local document links, registration targets and basic text hygiene.

These checks cover the shared stack, not all application projects. Projects retain
their own commands; use the relevant
project instructions and tests as well. Kizen configuration must be checked against
current CLI schemas/dry-run output, not an invented generic JSON lint schema.

A suppression needs the narrow rule and a concrete reason. Reviewers should reject
blanket ignores or disabling a gate just to ship. If a rule is wrong, correct the
rule and add a regression showing the intended allowed and rejected behavior.
