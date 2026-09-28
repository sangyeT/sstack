# Rebuild context before choosing a solution

Use for ambiguous bugs, new boundaries, or resuming a project. Keep read-only
investigation read-only. Load only evidence relevant to the current question.

1. Restate the underlying user problem in your own words before accepting a
   proposed cause. Name the observable outcome and what remains uncertain.
2. Trace one real input through entry point, validation, state changes, downstream
   effects, and visible result. Cite exact source paths and versions. For Kizen,
   resolve object grain, automation/child runs, field ownership, and intended role.
3. Recover motivation independently: relevant commits/PR discussions, linked Jira
   issues, design docs and user-provided conversations. Discover tools available
   on the current host. Do not guess unavailable history or search unrelated
   personal data. Code demonstrates mechanics; history may explain intent.
4. On resume, recover the prior goal, decisions and evidence from accessible task
   history and durable Jira/PR checkpoints. Check the actual branch/head, dirty
   files, current owner and deployed state. Treat old summaries as leads. Stop a
   prior writer before replacing it; chat recall does not transfer its checkout.
5. For each unresolved factual question choose the smallest discriminating read,
   reproduction or experiment. Distinguish observed facts, historical statements,
   hypotheses and product preferences. Ask only for a consequential preference
   or unavailable fact that blocks the outcome.
6. Return a compact grounding brief: problem, execution path, constraints with
   citations, hypotheses and counterevidence, next experiment, open decisions.
   Explain the result in user terms, then the implementation implications. Do not
   dump transcripts or claim that agreeing agents are independent evidence.

For broad investigations, delegate bounded source slices to read-only workers
when authorized; each returns citations and uncertainties. The coordinator checks
conflicts and synthesizes one account. Never delegate live mutations as research.
