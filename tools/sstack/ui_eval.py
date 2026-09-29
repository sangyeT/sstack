#!/usr/bin/env python3
"""Drive a scripted browser path and record per-step UI evidence for visual review."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[2]
ACTIONS = {
    "goto": {"path"},
    "click": {"selector"},
    "fill": {"selector", "value"},
    "press": {"selector", "key"},
    "wait_for": {"selector"},
    "expect_text": {"selector", "text"},
    "capture": {"selector", "case", "key"},
}
STEP_OPTIONAL = {"id", "timeout_ms"}
SCRIPT_REQUIRED = {"schema_version", "base_url", "steps"}
SCRIPT_OPTIONAL = {"viewport", "ignore_console"}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
MARKER = "{run_marker}"
# One standalone number: not glued to letters, other digits or separators.
NUMBER = re.compile(r"(?<![\w.,-])-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![.,]?\d|-?\w)")
QUERY = re.compile(r"[?#][^\s\"'<>]*")
VERDICTS = {"pass", "fail"}
PROBLEMS = ("console_errors", "page_errors", "failed_requests", "blocked_navigations")


def origin(url):
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


def redact(text):
    """Drop URL queries and fragments, which can carry tokens or signed parameters."""
    return QUERY.sub("?…", text)[:300]


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name}: nonempty trimmed text required")


def validate_script(script):
    if not isinstance(script, dict) or not SCRIPT_REQUIRED <= set(script):
        raise ValueError("script: schema_version, base_url and steps required")
    if set(script) - SCRIPT_REQUIRED - SCRIPT_OPTIONAL:
        raise ValueError("script: unknown fields")
    if script["schema_version"] != 1 or type(script["schema_version"]) is not int:
        raise ValueError("script: unsupported schema_version")
    parts = urlsplit(script["base_url"]) if isinstance(script["base_url"], str) else None
    if (
        not parts
        or not parts.netloc
        or (
            parts.scheme != "https"
            and not (parts.scheme == "http" and parts.hostname in LOCAL_HOSTS)
        )
    ):
        raise ValueError("script: base_url must be https, or http on localhost")
    viewport = script.get("viewport", {"width": 1440, "height": 900})
    if not isinstance(viewport, dict) or set(viewport) != {"width", "height"}:
        raise ValueError("script: viewport needs width and height")
    if not all(type(value) is int and value > 0 for value in viewport.values()):
        raise ValueError("script: viewport values must be positive integers")
    ignore = script.get("ignore_console", [])
    if not isinstance(ignore, list):
        raise ValueError("script: ignore_console must be a list of patterns")
    for pattern in ignore:
        _text(pattern, "ignore_console")
        try:
            re.compile(pattern)
        except re.error as error:
            raise ValueError(f"ignore_console: invalid pattern {pattern!r}") from error
    steps = script["steps"]
    if not isinstance(steps, list) or not steps:
        raise ValueError("script: steps required")
    identifiers, captures = set(), set()
    for index, step in enumerate(steps, 1):
        if not isinstance(step, dict) or step.get("action") not in ACTIONS:
            raise ValueError(f"step {index}: unknown action")
        required = ACTIONS[step["action"]]
        optional = STEP_OPTIONAL | ({"as"} if step["action"] == "capture" else set())
        if not required <= set(step) or set(step) - required - optional - {"action"}:
            raise ValueError(f"step {index}: fields for {step['action']} are {sorted(required)}")
        for key in required:
            _text(step[key], f"step {index}.{key}")
        if step["action"] == "goto" and (
            not step["path"].startswith("/")
            or step["path"].startswith("//")
            or "\\" in step["path"]
            or origin(urljoin(script["base_url"], step["path"])) != origin(script["base_url"])
        ):
            raise ValueError(f"step {index}: goto path must start with / under base_url")
        if step.get("as", "text") not in {"text", "number"}:
            raise ValueError(f"step {index}: capture as must be text or number")
        if step["action"] == "capture":
            if (step["case"], step["key"]) in captures:
                raise ValueError(f"step {index}: duplicate capture of {step['case']}.{step['key']}")
            captures.add((step["case"], step["key"]))
        timeout = step.get("timeout_ms", 1)
        if type(timeout) is not int or timeout <= 0:
            raise ValueError(f"step {index}: timeout_ms must be a positive integer")
        identifier = step.get("id", f"step-{index}")
        _text(identifier, f"step {index}.id")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", identifier) or identifier in identifiers:
            raise ValueError(f"step {index}: id must be unique letters, digits, - or _")
        identifiers.add(identifier)
    return script


def check_storage_state(path, root=ROOT):
    resolved = Path(path).resolve()
    if resolved == Path(root).resolve() or Path(root).resolve() in resolved.parents:
        raise ValueError("storage state holds a login session; keep it outside the repository")
    if not resolved.is_file():
        raise ValueError("storage state file not found")
    return resolved


def captured(text, kind):
    if kind == "text":
        return text.strip()
    normalized = text.replace("−", "-")
    matches = list(NUMBER.finditer(normalized))
    if len(matches) != 1:
        raise ValueError(f"capture_needs_one_number: {text.strip()[:80]!r}")
    match = matches[0]
    number = float(match.group().replace(",", ""))
    before, after = normalized[: match.start()].rstrip(), normalized[match.end() :].lstrip()
    if before.endswith("(") and after.startswith(")"):
        number = -number
    return int(number) if number.is_integer() else number


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(
    script,
    *,
    approved_origin,
    out_dir,
    storage_state=None,
    headed=False,
    video=False,
    timeout_ms=15000,
    root=ROOT,
):
    """Run the script against the approved origin only; UI actions may write data."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import expect, sync_playwright

    validate_script(script)
    approved = origin(approved_origin)
    if origin(script["base_url"]) != approved:
        raise ValueError("base_url origin differs from the approved origin")
    if storage_state:
        storage_state = check_storage_state(storage_state, root)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    marker = "sstack-" + secrets.token_hex(4)
    ignore = [re.compile(pattern) for pattern in script.get("ignore_console", [])]
    problems = {kind: [] for kind in PROBLEMS}
    popups = []

    def console(message):
        if message.type == "error" and not any(p.search(message.text) for p in ignore):
            problems["console_errors"].append(redact(message.text))

    def top_level(request):
        if not request.is_navigation_request():
            return False
        try:
            return request.frame.parent_frame is None
        except PlaywrightError:
            return True  # A popup's first navigation precedes its frame.

    def response(item):
        top = top_level(item.request)
        if origin(item.url) == approved and (item.status >= 500 or (top and item.status >= 400)):
            problems["failed_requests"].append(redact(f"{item.status} {item.url}"))

    def failed_request(request):
        if origin(request.url) == approved:
            problems["failed_requests"].append(
                redact(f"{request.method} {request.url} {request.failure}")
            )

    def block(url, route):
        problems["blocked_navigations"].append(redact(url))
        route.abort()

    def guard(route):
        request = route.request
        if not top_level(request):
            route.continue_()
        elif origin(request.url) != approved:
            block(request.url, route)
        else:
            # Browsers follow network redirects without routing them, so fetch top-level
            # pages here and check each redirect target before the browser follows it.
            try:
                fetched = route.fetch(max_redirects=0)
            except PlaywrightError:
                route.abort()
                return
            location = fetched.headers.get("location")
            if 300 <= fetched.status < 400 and location:
                target = urljoin(request.url, location)
                if origin(target) != approved:
                    block(target, route)
                    return
            route.fulfill(response=fetched)

    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    started = time.monotonic()
    steps, observed, evidence = [], {}, {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not headed)
        options = {"viewport": script.get("viewport", {"width": 1440, "height": 900})}
        if storage_state:
            options["storage_state"] = str(storage_state)
        if video:
            options["record_video_dir"] = str(out / "video")
        context = browser.new_context(**options)
        context.route("**/*", guard)
        context.on("console", console)
        context.on(
            "weberror", lambda error: problems["page_errors"].append(redact(str(error.error)))
        )
        context.on("response", response)
        context.on("requestfailed", failed_request)
        page = context.new_page()
        context.on("page", lambda opened: popups.append(redact(opened.url)))
        failed = False
        for index, step in enumerate(script["steps"], 1):
            identifier = step.get("id", f"step-{index}")
            record = {"index": index, "id": identifier, "action": step["action"]}
            if failed:
                steps.append({**record, "status": "skipped"})
                continue
            timeout = step.get("timeout_ms", timeout_ms)
            blocked = len(problems["blocked_navigations"])
            step_started = time.monotonic()
            value = None
            try:
                selector = step.get("selector")
                locator = page.locator(selector) if selector else None
                action = step["action"]
                if action == "goto":
                    path = step["path"].replace(MARKER, marker)
                    target = urljoin(script["base_url"], path)
                    if origin(target) != approved:
                        raise ValueError("off_origin_navigation: goto target")
                    page.goto(target, timeout=timeout)
                elif action == "click":
                    locator.click(timeout=timeout)
                elif action == "fill":
                    locator.fill(step["value"].replace(MARKER, marker), timeout=timeout)
                elif action == "press":
                    locator.press(step["key"], timeout=timeout)
                elif action == "wait_for":
                    locator.wait_for(timeout=timeout)
                elif action == "expect_text":
                    expected = step["text"].replace(MARKER, marker)
                    expect(locator).to_contain_text(expected, timeout=timeout)
                else:
                    value = captured(locator.inner_text(timeout=timeout), step.get("as", "text"))
                if len(problems["blocked_navigations"]) > blocked:
                    raise ValueError("off_origin_navigation: blocked")
                if origin(page.url) != approved:
                    raise ValueError(f"off_origin_navigation: {origin(page.url)}")
                record["status"] = "passed"
            except (PlaywrightError, AssertionError, ValueError) as error:
                record["status"] = "failed"
                record["error"] = redact(str(error).splitlines()[0])
            if origin(page.url) == approved:
                screenshot = out / f"step-{index:02d}-{identifier}.png"
                try:
                    page.screenshot(path=str(screenshot), full_page=True)
                    record["screenshot"] = screenshot.name
                    record["screenshot_sha256"] = digest(screenshot)
                except PlaywrightError as error:
                    record["status"] = "failed"
                    record["screenshot_error"] = redact(str(error).splitlines()[0])
            else:
                record["status"] = "failed"
                record["screenshot_error"] = "page is off the approved origin"
            if record["status"] == "passed" and step["action"] == "capture":
                observed.setdefault(step["case"], {})[step["key"]] = value
                record["observed"] = value
                evidence.setdefault(step["case"], []).append(f"ui-screenshot:{screenshot.name}")
            failed = record["status"] == "failed"
            record["duration_seconds"] = round(time.monotonic() - step_started, 3)
            steps.append(record)
        if not failed:
            try:
                page.wait_for_load_state(timeout=timeout_ms)
                page.wait_for_timeout(500)
            except PlaywrightError as error:
                problems["page_errors"].append(redact(str(error).splitlines()[0]))
        browser_version = browser.version
        context.close()
        browser.close()
    passed = all(step["status"] == "passed" for step in steps) and not any(problems.values())
    report = {
        "schema_version": 1,
        "status": "passed" if passed else "failed",
        "visual_review": "pending",
        "base_url": script["base_url"],
        "script_sha256": hashlib.sha256(
            json.dumps(script, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "run_marker": marker,
        "browser": f"chromium {browser_version}",
        "started_at": started_at,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "steps": steps,
        **problems,
        "popups": popups,
        "eval_cases": [
            {"id": case, "observed": values, "evidence": evidence[case]}
            for case, values in observed.items()
        ],
        "scope": "automated UI checks only; screenshots need visual review",
    }
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def _report_steps(report):
    if not isinstance(report, dict) or report.get("status") not in {"passed", "failed"}:
        raise ValueError("report: not a ui_eval run report")
    steps = report.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("report: steps required")
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("id"), str):
            raise ValueError("report: malformed step")
        if step.get("status") != "skipped" and not isinstance(step.get("screenshot"), str):
            raise ValueError(f"report: step {step['id']} has no screenshot to review")
    return {step["id"]: step for step in steps if step.get("status") != "skipped"}


def review(report_path, verdicts):
    """Bind an agent's per-screenshot visual verdicts to the recorded evidence."""
    report_path = Path(report_path)
    report = json.loads(report_path.read_text())
    shots = _report_steps(report)
    if not isinstance(verdicts, dict) or set(verdicts) != {"reviewer", "steps"}:
        raise ValueError("verdicts: reviewer and steps required")
    _text(verdicts["reviewer"], "reviewer")
    given = verdicts["steps"]
    if not isinstance(given, dict):
        raise ValueError("verdicts: steps must map step ids to verdicts")
    if set(given) - set(shots):
        raise ValueError("verdicts: unknown or skipped step ids")
    reasons, results = [], {}
    for identifier, step in shots.items():
        if digest(report_path.parent / step["screenshot"]) != step.get("screenshot_sha256"):
            raise ValueError(f"screenshot changed since the run: {step['screenshot']}")
        verdict = given.get(identifier)
        if verdict is None:
            reasons.append(f"missing_verdict:{identifier}")
            continue
        if (
            not isinstance(verdict, dict)
            or set(verdict) != {"verdict", "note"}
            or verdict["verdict"] not in VERDICTS
        ):
            raise ValueError(f"verdicts.{identifier}: verdict pass or fail and a note required")
        _text(verdict["note"], f"verdicts.{identifier}.note")
        results[identifier] = {**verdict, "screenshot_sha256": step["screenshot_sha256"]}
        if verdict["verdict"] == "fail":
            reasons.append(f"visual_fail:{identifier}")
    if report["status"] != "passed":
        reasons.append("automated_checks_failed")
    if any(reason.startswith("missing_verdict") for reason in reasons):
        status = "blocked"
    else:
        status = "failed" if reasons else "passed"
    summary = {
        "schema_version": 1,
        "status": status,
        "reasons": reasons,
        "reviewer": verdicts["reviewer"],
        "report_sha256": digest(report_path),
        "steps": results,
        "scope": "reviewer-declared visual verdicts; not authenticated by this tool",
    }
    (report_path.parent / "review.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    runner = commands.add_parser("run", help="Run a UI script and save per-step evidence")
    runner.add_argument("script")
    runner.add_argument("--approved-origin", required=True)
    runner.add_argument("--storage-state")
    runner.add_argument("--out")
    runner.add_argument("--headed", action="store_true")
    runner.add_argument("--video", action="store_true")
    runner.add_argument("--timeout-ms", type=int, default=15000)
    reviewer = commands.add_parser("review", help="Record visual verdicts for a run")
    reviewer.add_argument("report")
    reviewer.add_argument("verdicts")
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            out = args.out or ROOT / "artifacts/sstack/ui" / f"{stamp}-{secrets.token_hex(4)}"
            result = run(
                json.loads(Path(args.script).read_text()),
                approved_origin=args.approved_origin,
                out_dir=out,
                storage_state=args.storage_state,
                headed=args.headed,
                video=args.video,
                timeout_ms=args.timeout_ms,
            )
            result = {**result, "report": str(Path(out) / "report.json")}
        else:
            result = review(args.report, json.loads(Path(args.verdicts).read_text()))
    except ImportError:
        result = {"status": "blocked", "reasons": ["install playwright from requirements-dev"]}
    except (OSError, ValueError) as error:
        result = {"status": "blocked", "reasons": [str(error)]}
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
