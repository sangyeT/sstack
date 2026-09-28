# SStack

A shared PM → engineer → verification → review → merge workflow for **Claude Code
and Codex**, designed for individual repositories and monorepos. SStack evolves
the Kizen Stack into a portable skill bundle, with Kizen-first design when the
project uses Kizen.

Give the PM a goal and project folder. It breaks the outcome into Jira work,
assigns ready tickets to engineer agents, validates the results, coordinates
independent review, merges eligible PRs, verifies required rollout, updates Jira,
and picks up the next ticket within the goal. Failed gates return work for fixes;
an open PR or a merged configuration file alone is not delivery proof.

## Install into a repository

Requires Git, Python 3.9+ and a filesystem that supports symlinks. Clone SStack:

```sh
git clone https://github.com/sangyeT/sstack.git
cd sstack
python3 install.py --repo /absolute/path/to/your-repo --plan
python3 install.py --repo /absolute/path/to/your-repo
```

The installer copies the tools and installer, registers the same canonical skills
under `.claude/skills` and `.agents/skills`, and adds managed instructions to
`AGENTS.md` and `CLAUDE.md`, plus ignore rules for generated evidence and caches.
It preserves existing content and refuses conflicting
files. It does not install account-wide skills, credentials, a scheduler or CI in
the consuming repository. Review and commit the installed files in that repository.
Matching reruns are safe; an upgrade that conflicts with locally modified files
requires a reviewed reconciliation.

Open **that repository** in Claude Code or Codex and start a fresh session:

```text
/sstack Build a portfolio tracker in projects/portfolio.
Start with manual holdings entry and show allocation by asset class.
```

In Codex, use `$sstack` or say `PM: <goal and project folder>`. Claude Code uses
`/sstack`. If discovery is unavailable, ask the agent to read
`tools/sstack/skills/sstack/SKILL.md`. Local repository skills are not automatically
uploaded to Claude's web chat or ChatGPT. The two hosts share procedures and files;
their tools, credentials, conversation history and running agents remain separate.

| Skill | Purpose |
| --- | --- |
| `sstack` | PM intake, Jira breakdown, dispatch and delivery coordination |
| `sstack-engineer` | Implement a scoped ticket and return tested PR evidence |
| `sstack-mode` | Research, design, prototypes and direct project work |
| `sstack-verify` | Validate behavior and maintain project verification recipes |

## Set or change the PM board

No board is hardcoded. From the **target repository root**, save its Jira board:

```sh
python3 tools/sstack/control.py board set \
  'https://example.atlassian.net/jira/software/projects/APP/boards/12' \
  --project-key APP
python3 tools/sstack/control.py board show
```

A monorepo project can use a different board:

```sh
python3 tools/sstack/control.py board set \
  'https://example.atlassian.net/jira/software/projects/FIN/boards/34' \
  --project-key FIN --project-path projects/portfolio
python3 tools/sstack/control.py board show --project-path projects/portfolio
python3 tools/sstack/control.py board clear --project-path projects/portfolio
```

You can also tell the PM: **“Set the PM board for projects/portfolio to <link>,
project key FIN.”** An explicit board for one goal takes precedence, then the
longest matching project-folder setting, then the repository default. Saved
settings are in `.sstack.json`. A URL does not grant access: the PM verifies the
actual destination and uses the host's authenticated Jira tools or browser.
Current delivery support is Jira; saving another service's URL does not implement
an integration for it.

## Register projects and verification

The starter registry, `tools/sstack/projects.json`, covers the stack itself.
Register each project's owned paths, offline suites, external proof routes and
real dependencies before dispatch. Unknown changed paths block verification.
Custom suites are reviewed executable configuration, not commands copied blindly
from tickets. For example, a suite entry can run an existing test file:

```json
"suites": {
  "portfolio": [
    {"name": "portfolio-tests", "cwd": "projects/portfolio",
     "command": ["$PYTHON", "checks.py"]}
  ]
}
```

Add a corresponding `projects` entry with `id`, `paths`, `suites`, `external` and
`affects`. `$PYTHON` uses the controller's interpreter; commands run without a
shell. Reuse existing feature documentation and tests. PM defines additional
small evaluation sets only where acceptance needs them, before implementation.
See the [tool and delivery protocol](tools/sstack/README.md) for schemas, evidence,
claims, recovery and external verification.

## Check the stack

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r tools/sstack/requirements-dev.txt
.venv/bin/python tools/sstack/lint.py
.venv/bin/python tools/sstack/control.py verify stack
```

The included GitHub workflow checks this repository's lint, contracts, tests and
changed-path coverage. Product acceptance still requires the affected project's
checks and any declared live/UI proof. Repository protection and required checks
must be configured separately.

## Autonomy and operating limits

Routine delivery gates are automated evidence checks. Human input is for concrete
missing decisions, access or required environment approval. Kizen applies still
follow the documented dry-run/apply boundary. A Git merge merges versioned code
and configuration; live deployment needs its own observed result.

The local delivery controller persists checkpoints and atomic leases for one
coordinator clone and its worktrees on one host, with one Jira site per coordinator.
Keep each in-flight ticket's issue URL/site fixed when changing board defaults.
It supports bounded recovery,
but cannot coordinate separate computers or authenticate arbitrary agent-provided
business observations. Fully unattended operation requires a trusted host worker
adapter and an explicitly launched runner or scheduler; neither is supplied as
an always-running service. The test suite proves local behavior, not a measured
production unattended-delivery success rate.

Inspired by [Lauren Tan's Pstack](https://github.com/cursor/plugins/tree/main/pstack),
adapted for Kizen and cross-host delivery. SStack's Kizen-first design rules are
project conventions, not an official Kizen principles publication.
