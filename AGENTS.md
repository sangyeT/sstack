# SStack

SStack is a shared PM, engineering and verification workflow for Claude Code and
Codex. Canonical skills and tools live in tools/sstack; .claude/skills and
.agents/skills link to them. Read the applicable skill before changing procedures.

Use /sstack plus a project goal for PM delivery. Read tools/sstack/skills/sstack/SKILL.md.
Resolve the target project, its instructions and configured PM board before posting.
Do not default to a previous customer, board, environment or credential.

Use /sstack-demo for demos. Demo work stays on demo/* branches, never merges to
the default branch and is never ticket completion evidence. It follows that
skill's own checks instead of delivery review and gates.

Use independent engineer/reviewer agents for meaningful changes. Parallel writers
need isolated Git worktrees and nonconflicting live resources. Routine scoped
validation, commits, pushes and PRs proceed within the authorized task. Respect
explicit merge limits and actual environment-specific apply approvals.

Prefer the smallest complete, verified solution. Reuse existing code and native
Kizen capabilities when appropriate; do not force non-Kizen projects onto Kizen.
Remove redundant comments; preserve non-obvious constraints and required notices.
Answer in chat by default. Create artifacts only when requested or necessary for
implementation, verification or handoff; update existing records instead of
duplicating them. Keep secrets and private customer data out of shared evidence.

Run python tools/sstack/control.py verify changed --base <actual-base> --jobs 2
with pinned development dependencies. This selects docs checks or shared lint/tests
and affected project suites; do not duplicate the selected commands. Runtime and
skill changes require the full stack gate. Use one independent verifier/reviewer
by default and overlap it with safe checks on a stable commit. See the delivery
contract for risk escalation and exact-input evidence reuse. Use verify stack for
an explicit full regression or when no comparison base exists.
Report actual evidence and operating limits. The local delivery store coordinates
one clone and its worktrees on one host, not independent clones or computers.
