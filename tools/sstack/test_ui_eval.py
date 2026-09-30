import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import ui_eval

PAGES = {
    "/": """<!doctype html><title>Allocation</title>
<label>Stocks <input id="stocks"></label><label>Bonds <input id="bonds"></label>
<button id="go" onclick="
  const s = +stocks.value, b = +bonds.value, t = s + b;
  result.textContent = 'Stocks ' + Math.round(100 * s / t) + '%';
  owner.textContent = note.value;">Show</button>
<input id="note"><p id="result"></p><p id="owner"></p>
<a id="away" href="http://localhost:{port}/away">Away</a>
<button id="later" onclick="setTimeout(() => location = 'http://localhost:{port}/later', 50)">
Later</button>
<button id="popup" onclick="window.open('http://localhost:{port}/popup')">Popup</button>
<button id="noisy" onclick="console.error('boom')">Noisy</button>
<button id="throw" onclick="setTimeout(() => { throw new Error('kaput') })">Throw</button>
<button id="broken" onclick="fetch('/boom?token=secret')">Broken</button>""",
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.hosts.append(self.headers["Host"].split(":")[0])
        path = self.path.split("?")[0]
        redirects = {
            "/home": "/",
            "/chain": "/home",
            "/leave": f"http://localhost:{self.server.server_port}/x",
            "/hop": "/leave",
            "/loop": "/loop",
        }
        if path in redirects:
            self.send_response(302)
            self.send_header("Location", redirects[path])
            self.end_headers()
            return
        page = PAGES.get(path)
        status = 200 if page else 500 if path == "/boom" else 404
        body = (page or "missing").replace("{port}", str(self.server.server_port)).encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def script(base, *steps):
    return {
        "schema_version": 1,
        "base_url": base,
        "steps": [{"action": "goto", "path": "/"}, *steps],
    }


def capture(**extra):
    return {"action": "capture", "selector": "x", "case": "c", "key": "k", **extra}


class ValidationTests(unittest.TestCase):
    def test_rejects_unsafe_or_malformed_scripts(self):
        base = "https://a.test"
        cases = [
            {"schema_version": 1, "base_url": "http://example.com", "steps": [{}]},
            *(
                script(base, {"action": "goto", "path": path})
                for path in (
                    "https://b.test/",
                    "//b.test/",
                    "/\\b.test/",
                    "http:b.test/x",
                    "file:///etc/passwd",
                    "javascript:alert(1)",
                    "records",
                )
            ),
            script(base, {"action": "click"}),
            script(base, {"action": "eval", "selector": "x"}),
            script(base, {"action": "click", "selector": "x", "id": "bad id"}),
            script(base, capture(**{"as": "html"})),
            script(base, capture(), capture(id="again")),
            script(base, capture(case=" c")),
            {**script(base), "ignore_console": ["("]},
            {**script(base), "extra": True},
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                ui_eval.validate_script(case)
        ui_eval.validate_script(script("http://127.0.0.1:8000", capture()))

    def test_storage_state_must_live_outside_repository(self):
        with tempfile.TemporaryDirectory() as root:
            inside = Path(root, "state.json")
            inside.write_text("{}")
            with self.assertRaises(ValueError):
                ui_eval.check_storage_state(inside, root)
            with tempfile.NamedTemporaryFile(suffix=".json") as outside:
                self.assertEqual(
                    ui_eval.check_storage_state(outside.name, root), Path(outside.name).resolve()
                )

    def test_numeric_capture_takes_exactly_one_standalone_number(self):
        for text, expected in [
            ("Stocks 60%", 60),
            ("60.0%", 60),
            ("$1,234.50", 1234.5),
            ("Q3 total 60", 60),
            ("Item-5 total 60", 60),
            ("Change -12", -12),
            ("Change −12", -12),
            ("(1,234)", -1234),
        ]:
            with self.subTest(text=text):
                self.assertEqual(ui_eval.captured(text, "number"), expected)
        for text in ("none", "1,2,3", "1.234,5", "60% of 100", "5-10", "2024-01-05", "1e5"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                ui_eval.captured(text, "number")

    def test_review_rejects_reports_without_reviewable_screenshots(self):
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder, "report.json")
            verdicts = {"reviewer": "r", "steps": {}}
            for content in (
                [],
                {"status": "passed"},
                {"status": "passed", "steps": []},
                {"status": "passed", "steps": [{"status": "passed"}]},
                {"status": "passed", "steps": [{"id": "a", "status": "passed"}]},
            ):
                report.write_text(json.dumps(content))
                with self.subTest(content=content), self.assertRaises(ValueError):
                    ui_eval.review(report, verdicts)


def require_browser():
    try:
        from playwright.sync_api import Error, sync_playwright

        with sync_playwright() as playwright:
            playwright.chromium.launch().close()
    except (ImportError, Error) as error:
        if os.environ.get("SSTACK_REQUIRE_BROWSER"):
            raise
        raise unittest.SkipTest(f"Chromium unavailable: {type(error).__name__}") from error


def alive(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def serve(port, site, *, before="", requests=None, status=None):
    """Python source for a launched test server; optional setup, request limit or status."""
    handler = "http.server.SimpleHTTPRequestHandler"
    if status:
        handler = "Always"
    loop = f"[s.handle_request() for _ in range({requests})]" if requests else "s.serve_forever()"
    return f"""import functools, http.server, os, signal, subprocess, sys, time
class Always(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response({status or 200}); self.end_headers()
{before}
s = http.server.ThreadingHTTPServer(
    ("127.0.0.1", {port}), functools.partial({handler}, directory={str(site)!r})
    if {handler!r} != "Always" else Always)
{loop}
"""


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class LaunchValidationTests(unittest.TestCase):
    def test_rejects_unsafe_or_malformed_launch_files(self):
        good = {"command": ["$PYTHON", "-m", "http.server"], "cwd": "tools/sstack"}
        self.assertEqual(ui_eval.validate_launch(good)["command"][0], ui_eval.sys.executable)
        for launch in (
            {**good, "command": "python -m http.server"},
            {**good, "command": []},
            {**good, "cwd": "../.."},
            {**good, "cwd": "missing-dir"},
            {**good, "ready_path": "//evil.test"},
            {**good, "ready_timeout_s": 0},
            {**good, "stop_grace_s": 120},
            {**good, "env": {"A": 1}},
            {**good, "shell": True},
            {"command": ["x"]},
        ):
            with self.subTest(launch=launch), self.assertRaises(ValueError):
                ui_eval.validate_launch(launch)

    def test_record_requires_a_local_base_url(self):
        launch = {"command": ["$PYTHON", "-m", "http.server"], "cwd": "tools/sstack"}
        with tempfile.TemporaryDirectory() as out, self.assertRaises(ValueError):
            ui_eval.record(script("https://sandbox.example.test"), launch, out_dir=out)


class RecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_browser()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.out = Path(temp.name, "out")
        self.site = Path(temp.name, "site")
        self.site.mkdir()
        (self.site / "index.html").write_text(
            PAGES["/"].replace("{port}", "1") + '<a id="about" href="/about.html">About</a>'
        )
        (self.site / "about.html").write_text("<h1 id='title'>About the demo</h1>")
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"

    def launch(self, *command, **extra):
        command = command or (
            "$PYTHON", "-m", "http.server", str(self.port),
            "--bind", "127.0.0.1", "--directory", str(self.site),
        )  # fmt: skip
        return {"command": list(command), "cwd": "tools/sstack", "ready_timeout_s": 15, **extra}

    def test_starts_app_records_video_and_stops_only_its_server(self):
        report = ui_eval.record(
            script(
                self.base,
                {"action": "click", "selector": "#about"},
                {"action": "expect_text", "selector": "#title", "text": "About the demo"},
            ),
            self.launch(),
            out_dir=self.out,
        )
        self.assertEqual(report["status"], "passed", report)
        self.assertEqual(report["reasons"], [])
        self.assertTrue(report["videos"], report)
        for video in report["videos"]:
            self.assertEqual(ui_eval.digest(self.out / video["file"]), video["sha256"])
        self.assertIn("ready_seconds", report["server"])
        self.assertIsNotNone(report["server"]["exit_code"])
        self.assertTrue((self.out / "server.log").is_file())
        self.assertFalse(ui_eval.responds(self.base + "/"))
        saved = json.loads((self.out / "report.json").read_text())
        self.assertEqual(saved["server"]["pid"], report["server"]["pid"])

    def test_server_that_exits_or_never_answers_fails_without_a_browser_run(self):
        for command, reason in (
            (("$PYTHON", "-c", "import sys; sys.exit(3)"), "server_exited_before_ready"),
            (("$PYTHON", "-c", "import time; time.sleep(60)"), "server_not_ready"),
        ):
            with self.subTest(reason=reason):
                started = ui_eval.time.monotonic()
                report = ui_eval.record(
                    script(self.base),
                    self.launch(*command, ready_timeout_s=1),
                    out_dir=self.out,
                )
                self.assertEqual((report["status"], report["reasons"]), ("failed", [reason]))
                self.assertEqual((report["steps"], report["videos"]), ([], []))
                reviewed = ui_eval.review(self.out / "report.json", {"reviewer": "r", "steps": {}})
                self.assertEqual(reviewed["status"], "failed")
                self.assertIn(reason, reviewed["reasons"])
                self.assertIsNotNone(report["server"]["exit_code"])
                self.assertLess(ui_eval.time.monotonic() - started, 15)

    def test_refuses_to_record_against_a_server_it_did_not_start(self):
        stale = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        stale.hosts = []
        threading.Thread(target=stale.serve_forever, daemon=True).start()
        self.addCleanup(stale.server_close)
        self.addCleanup(stale.shutdown)
        with self.assertRaises(ValueError):
            ui_eval.record(script(self.base), self.launch(), out_dir=self.out)
        self.assertFalse((self.out / "server.log").exists())

    def python(self, source, **extra):
        return self.launch("$PYTHON", "-c", source, **extra)

    def test_stops_children_that_ignore_sigterm_or_outlive_the_leader(self):
        pidfile = self.site.parent / "child.pid"
        spawn = (
            "c = subprocess.Popen([sys.executable, '-c', 'import signal, time; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(120)'])\n"
            f"open({str(pidfile)!r}, 'w').write(str(c.pid))"
        )
        for exits_first in (False, True):
            with self.subTest(leader_exits_first=exits_first):
                source = serve(self.port, self.site, before=spawn)
                if exits_first:
                    source = source.replace("s.serve_forever()", "sys.exit(0)")
                report = ui_eval.record(
                    script(self.base),
                    self.python(source, ready_timeout_s=5, stop_grace_s=1),
                    out_dir=self.out,
                )
                child = int(pidfile.read_text())
                self.assertFalse(alive(child), f"child {child} survived")
                expected = ["server_exited_before_ready"] if exits_first else []
                self.assertEqual(report["reasons"], expected, report)

    def test_server_exiting_during_run_and_error_status_fail(self):
        report = ui_eval.record(
            script(self.base, {"action": "wait_for", "selector": "#go"}),
            self.python(serve(self.port, self.site, requests=2)),
            out_dir=self.out,
        )
        self.assertEqual(report["status"], "failed")
        self.assertIn("server_exited_during_run", report["reasons"])
        busy = ui_eval.record(
            script(self.base),
            self.python(serve(self.port, self.site, status=503), ready_timeout_s=1),
            out_dir=self.out,
        )
        self.assertEqual(busy["reasons"], ["server_not_ready"])

    def test_report_omits_env_values_and_lists_only_this_runs_videos(self):
        launch = self.launch(env={"DEMO_TOKEN": "s3cret-value"})
        for _ in range(2):
            report = ui_eval.record(script(self.base), launch, out_dir=self.out)
        self.assertEqual(report["status"], "passed", report)
        self.assertEqual(len(report["videos"]), 1)
        self.assertEqual(report["server"]["env_keys"], ["DEMO_TOKEN"])
        self.assertEqual(report["server"]["cwd"], "tools/sstack")
        self.assertNotIn("s3cret-value", (self.out / "report.json").read_text())

    def test_sigterm_to_record_still_stops_the_server(self):
        driver = (
            "import json, sys, ui_eval\n"
            "ui_eval.record(json.loads(sys.argv[1]), json.loads(sys.argv[2]), out_dir=sys.argv[3])"
        )
        slow = script(self.base, {"action": "wait_for", "selector": "#never", "timeout_ms": 60000})
        parent = subprocess.Popen(
            [sys.executable, "-c", driver, json.dumps(slow), json.dumps(self.launch()),
             str(self.out)],
            cwd=Path(ui_eval.__file__).parent,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )  # fmt: skip
        self.addCleanup(parent.kill)
        deadline = ui_eval.time.monotonic() + 20
        while not ui_eval.listening(self.base) and ui_eval.time.monotonic() < deadline:
            ui_eval.time.sleep(0.1)
        self.assertTrue(ui_eval.listening(self.base), "server never started")
        ui_eval.time.sleep(1)
        parent.send_signal(signal.SIGTERM)
        parent.wait(timeout=30)
        self.assertFalse(ui_eval.listening(self.base), "server survived SIGTERM to record")


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_browser()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.hosts = []
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.out = Path(temp.name)
        self.server.hosts.clear()

    def run_script(self, *steps, **extra):
        return ui_eval.run(
            {**script(self.base, *steps), **extra}, approved_origin=self.base, out_dir=self.out
        )

    def click(self, selector, **extra):
        return {"action": "click", "selector": selector, **extra}

    def test_scripted_path_captures_values_screenshots_and_review(self):
        report = self.run_script(
            {"action": "fill", "selector": "#stocks", "value": "6000"},
            {"action": "fill", "selector": "#bonds", "value": "4000"},
            {"action": "fill", "selector": "#note", "value": "{run_marker}"},
            self.click("#go", id="show"),
            {"action": "expect_text", "selector": "#owner", "text": "{run_marker}"},
            {
                "action": "capture",
                "selector": "#result",
                "case": "mixed",
                "key": "stocks_pct",
                "as": "number",
                "id": "chart",
            },
        )
        self.assertEqual(report["status"], "passed", report)
        self.assertEqual(report["visual_review"], "pending")
        self.assertEqual(
            report["eval_cases"],
            [
                {
                    "id": "mixed",
                    "observed": {"stocks_pct": 60},
                    "evidence": ["ui-screenshot:step-07-chart.png"],
                }
            ],
        )
        self.assertTrue(all((self.out / step["screenshot"]).is_file() for step in report["steps"]))
        saved = json.loads((self.out / "report.json").read_text())
        self.assertEqual(saved["run_marker"], report["run_marker"])

        ids = [step["id"] for step in report["steps"]]
        verdict = {"verdict": "pass", "note": "Chart label reads 60%"}
        partial = {"reviewer": "demo-verifier", "steps": {"chart": verdict}}
        self.assertEqual(ui_eval.review(self.out / "report.json", partial)["status"], "blocked")
        complete = {"reviewer": "demo-verifier", "steps": dict.fromkeys(ids, verdict)}
        self.assertEqual(ui_eval.review(self.out / "report.json", complete)["status"], "passed")
        complete["steps"]["chart"] = {"verdict": "fail", "note": "Label clipped"}
        rejected = ui_eval.review(self.out / "report.json", complete)
        self.assertEqual(rejected["reasons"], ["visual_fail:chart"])
        (self.out / "step-07-chart.png").write_bytes(b"swapped")
        with self.assertRaises(ValueError):
            ui_eval.review(self.out / "report.json", complete)

    def test_failed_expectation_stops_later_steps_and_fails_review(self):
        report = self.run_script(
            {"action": "expect_text", "selector": "#result", "text": "never", "timeout_ms": 300},
            self.click("#go"),
        )
        self.assertEqual(report["status"], "failed")
        self.assertEqual([s["status"] for s in report["steps"]], ["passed", "failed", "skipped"])
        self.assertIn("screenshot", report["steps"][1])
        ids = [step["id"] for step in report["steps"][:2]]
        verdicts = {"reviewer": "r", "steps": dict.fromkeys(ids, {"verdict": "pass", "note": "ok"})}
        result = ui_eval.review(self.out / "report.json", verdicts)
        self.assertEqual(
            (result["status"], result["reasons"]), ("failed", ["automated_checks_failed"])
        )

    def test_console_errors_fail_unless_ignored(self):
        noisy = self.click("#noisy")
        self.assertEqual(self.run_script(noisy)["console_errors"], ["boom"])
        report = self.run_script(noisy, ignore_console=["^boom$"])
        self.assertEqual(report["status"], "passed", report)

    def test_page_errors_and_server_errors_fail_with_redacted_urls(self):
        wait = {"action": "wait_for", "selector": "#go", "timeout_ms": 300}
        thrown = self.run_script(self.click("#throw"), wait, wait, ignore_console=[".*"])
        self.assertEqual(thrown["status"], "failed")
        self.assertIn("kaput", thrown["page_errors"][0])
        broken = self.run_script(self.click("#broken"), wait, wait, ignore_console=[".*"])
        self.assertEqual(broken["status"], "failed")
        self.assertEqual(broken["failed_requests"], [f"500 {self.base}/boom?…"])
        self.assertNotIn("secret", json.dumps(broken))

    def test_missing_top_level_page_fails(self):
        report = ui_eval.run(
            {
                "schema_version": 1,
                "base_url": self.base,
                "steps": [{"action": "goto", "path": "/x"}],
            },
            approved_origin=self.base,
            out_dir=self.out,
        )
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["failed_requests"], [f"404 {self.base}/x"])

    def test_off_origin_navigation_is_blocked_before_any_request(self):
        for trigger in ("#away", "#later", "#popup"):
            with self.subTest(trigger=trigger):
                self.server.hosts.clear()
                wait = {"action": "wait_for", "selector": "#go", "timeout_ms": 300}
                report = self.run_script(self.click(trigger), wait, wait)
                self.assertEqual(report["status"], "failed", report)
                self.assertTrue(report["blocked_navigations"], report)
                self.assertNotIn("localhost", self.server.hosts)

    def test_redirects_are_checked_before_the_browser_follows_them(self):
        chain = self.run_script({"action": "goto", "path": "/chain"}, self.click("#go"))
        self.assertEqual(chain["status"], "passed", chain)
        away = f"http://localhost:{self.server.server_port}/x"
        for path in ("/leave", "/hop", "/loop"):
            with self.subTest(path=path):
                self.server.hosts.clear()
                report = self.run_script({"action": "goto", "path": path})
                self.assertEqual(report["status"], "failed", report)
                self.assertTrue(report["blocked_navigations"], report)
                self.assertNotIn("localhost", self.server.hosts)
                if path != "/loop":
                    self.assertEqual(report["blocked_navigations"], [away])

    def test_navigation_after_the_last_step_is_caught(self):
        report = self.run_script(self.click("#later"))
        self.assertEqual(report["status"], "failed", report)
        self.assertTrue(report["blocked_navigations"], report)
        self.assertNotIn("localhost", self.server.hosts)

    def test_unapproved_origin_is_refused_before_launch(self):
        with self.assertRaises(ValueError):
            ui_eval.run(script(self.base), approved_origin="https://other.test", out_dir=self.out)
