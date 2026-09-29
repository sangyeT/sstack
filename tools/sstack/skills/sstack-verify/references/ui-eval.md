# Scripted UI evaluation

`tools/sstack/ui_eval.py` drives a JSON UI script in Chromium, screenshots every
step, and records console errors, page errors, failed requests and captured
values in one `report.json`. An agent then views each screenshot and records a
visual verdict. It is built for web UIs such as the Kizen UI but has not yet been
exercised against a live Kizen login (SSO, MFA, session expiry). It does not call
the Kizen API or prove that a record was persisted.

Install `tools/sstack/requirements-dev.txt` (includes Playwright) and, where no
Chromium is preinstalled, run `python -m playwright install chromium`.

## Script

```json
{"schema_version": 1, "base_url": "https://sandbox.example.test",
 "viewport": {"width": 1440, "height": 900}, "ignore_console": ["^Known noise$"],
 "steps": [
  {"id": "open", "action": "goto", "path": "/records"},
  {"action": "fill", "selector": "role=textbox[name=\"Name\"]", "value": "Demo {run_marker}"},
  {"id": "save", "action": "click", "selector": "role=button[name=\"Save\"]"},
  {"action": "expect_text", "selector": "role=main", "text": "Demo {run_marker}"},
  {"id": "chart", "action": "capture", "selector": "#allocation", "case": "mixed-holdings",
   "key": "stocks_pct", "as": "number"}
 ]}
```

Actions: `goto` (path relative to `base_url`), `click`, `fill`, `press`,
`wait_for`, `expect_text` and `capture`. Selectors use Playwright syntax; prefer
role and visible-text selectors over generated class names. `{run_marker}` is
replaced by a value unique to each run, so readback can match this run's records.
The first failed step stops the run; later steps are reported as skipped.
`capture` with `"as": "number"` needs exactly one standalone number in the text.
`ignore_console` patterns only suppress known console noise; they never hide page
errors or failed requests. Failed requests are network failures and 5xx responses
on the approved origin, plus 4xx responses for its top-level pages.

## Run and review

```sh
python tools/sstack/ui_eval.py run SCRIPT.json --approved-origin https://sandbox.example.test \
  --storage-state /outside/repo/ui-state.json [--video] [--headed]
python tools/sstack/ui_eval.py review artifacts/sstack/ui/<run>/report.json VERDICTS.json
```

- `--approved-origin` is the human-approved UI host. The script's `base_url` must
  match it and `goto` paths must stay under it. Top-level navigation elsewhere,
  including links, redirects, delayed scripts and popups, is aborted before the
  request is sent and fails the run. UI actions can write data, so the origin needs
  the same approval as any other write there; for Kizen follow
  [platform](platform.md) and use the confirmed UI host, which may differ from the
  API host.
- `--storage-state` is a saved login session and must live outside the repository.
  Create one with `npx playwright codegen --save-storage=<path> <ui-host>` and log
  in as the intended role. Never commit or share it.
- Visual review: view every `step-NN-<id>.png` yourself, with computer use or by
  opening the image, and compare it to the step's expected visible result. Check
  layout, labels, values and error states that the automated checks cannot see.
  Write `{"reviewer": "<id>", "steps": {"<step id>": {"verdict": "pass", "note":
  "..."}}}` covering every screenshotted step, then run `review`. It fails on any
  `fail` verdict or failed automated check, blocks on missing verdicts, and refuses
  screenshots changed since the run. Verdicts are the reviewer's declarations; the
  tool binds them to the screenshot hashes but cannot authenticate them.

`report.json` `eval_cases` already has the result-case shape (`id`, `observed`,
`evidence`) for `surface: "ui"` cases in the
[evaluation contract](../../sstack/references/jira-handoff.md#pm-owned-evaluation-sets).
Rendered values are UI proof only; persisted Kizen results still need readback.
Recorded URLs drop query strings and fragments. Reports and screenshots can still
show record data; use synthetic records and inspect them before sharing.
