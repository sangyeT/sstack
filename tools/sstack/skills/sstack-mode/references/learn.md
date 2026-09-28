# Turn lessons into reusable behavior

Use after a difficult task, repeated failure, or a broken verification recipe.
Keep normal successful tasks lightweight.

1. Identify the concrete failure or wasted step from logs/diffs and its cause.
   Distinguish product defects, missing tools, stale maps and unclear instructions.
2. Prefer an executable check, schema, or small reusable command over another
   paragraph of warnings. Add a regression that fails for the actual bad behavior.
3. Edit the narrowest owner: project feature recipe for local knowledge; shared
   skill only for a pattern that applies across projects. Never save credentials,
   patient payloads, unexplained tenant IDs or a one-off workaround as a rule.
4. Re-run the failed scenario with the change. Record what is proven and where
   evidence remains absent. Verification-only maintenance must not silently fix
   product behavior; create a separate bounded issue for that.
5. Summarize the lesson and resulting structural change in the delivery packet.
   Remove obsolete guidance once its replacement is verified. Do not accumulate
   permanent speculative plans or duplicate the same rules across all skills.

For changed skill behavior, use a bounded independent scenario evaluation:
provide a realistic request and raw fixture, not the desired verdict. Include
resume, missing access and stale evidence cases when relevant. A frontmatter
validator checks syntax, not decision quality. Cross-host compatibility requires
an actual host run; symlink validation alone is not proof of Claude execution.

For ticket evaluations, PM owns expected outcomes before dispatch. Promote a
reproduced failure into the narrowest existing test or evaluation baseline, with
synthetic inputs and an independently checked expected result. Add cases between
runs; changing a frozen plan requires a documented requirement correction, review
and refreshed evidence. Preserve failures in the measured history. Do not grow a
separate evaluation document when the test or existing issue can hold the lesson.
