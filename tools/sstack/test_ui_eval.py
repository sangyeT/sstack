import json
import os
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


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import Error, sync_playwright

            with sync_playwright() as playwright:
                playwright.chromium.launch().close()
        except (ImportError, Error) as error:
            if os.environ.get("SSTACK_REQUIRE_BROWSER"):
                raise
            raise unittest.SkipTest(f"Chromium unavailable: {type(error).__name__}") from error
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
