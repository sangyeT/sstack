import importlib.util
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import ui_eval

HAS_BROWSER = importlib.util.find_spec("playwright") is not None
PAGES = {
    "/": """<!doctype html><title>Allocation</title>
<label>Stocks <input id="stocks"></label><label>Bonds <input id="bonds"></label>
<button id="go" onclick="
  const s = +stocks.value, b = +bonds.value, t = s + b;
  result.textContent = 'Stocks ' + Math.round(100 * s / t) + '%';
  owner.textContent = note.value;">Show</button>
<input id="note"><p id="result"></p><p id="owner"></p>
<a id="away" href="http://localhost:{port}/">Away</a>
<button id="noisy" onclick="console.error('boom')">Noisy</button>""",
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        page = PAGES.get(self.path)
        body = (page or "missing").replace("{port}", str(self.server.server_port)).encode()
        self.send_response(200 if page else 404)
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


class ValidationTests(unittest.TestCase):
    def test_rejects_unsafe_or_malformed_scripts(self):
        cases = [
            {"schema_version": 1, "base_url": "http://example.com", "steps": [{}]},
            script("https://a.test", {"action": "goto", "path": "https://b.test/"}),
            script("https://a.test", {"action": "click"}),
            script("https://a.test", {"action": "eval", "selector": "x"}),
            script("https://a.test", {"action": "click", "selector": "x", "id": "bad id"}),
            script(
                "https://a.test",
                {"action": "capture", "selector": "x", "case": "c", "key": "k", "as": "html"},
            ),
            {**script("https://a.test"), "extra": True},
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                ui_eval.validate_script(case)
        ui_eval.validate_script(script("http://127.0.0.1:8000"))

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

    def test_numeric_capture_parses_displayed_values(self):
        self.assertEqual(ui_eval.captured("Stocks 60%", "number"), 60)
        self.assertEqual(ui_eval.captured("$1,234.50", "number"), 1234.5)
        with self.assertRaises(ValueError):
            ui_eval.captured("none", "number")


@unittest.skipUnless(
    HAS_BROWSER or os.environ.get("SSTACK_REQUIRE_BROWSER"), "playwright not installed"
)
class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
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

    def run_script(self, *steps):
        return ui_eval.run(script(self.base, *steps), approved_origin=self.base, out_dir=self.out)

    def test_scripted_path_captures_values_screenshots_and_review(self):
        report = self.run_script(
            {"action": "fill", "selector": "#stocks", "value": "6000"},
            {"action": "fill", "selector": "#bonds", "value": "4000"},
            {"action": "fill", "selector": "#note", "value": "{run_marker}"},
            {"action": "click", "selector": "#go", "id": "show"},
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

    def test_failed_expectation_stops_later_steps(self):
        report = self.run_script(
            {"action": "expect_text", "selector": "#result", "text": "never", "timeout_ms": 300},
            {"action": "click", "selector": "#go"},
        )
        self.assertEqual(report["status"], "failed")
        self.assertEqual([s["status"] for s in report["steps"]], ["passed", "failed", "skipped"])
        self.assertIn("screenshot", report["steps"][1])

    def test_console_errors_fail_unless_ignored(self):
        noisy = {"action": "click", "selector": "#noisy"}
        self.assertEqual(self.run_script(noisy)["console_errors"], ["boom"])
        quiet = {**script(self.base, noisy), "ignore_console": ["^boom$"]}
        report = ui_eval.run(quiet, approved_origin=self.base, out_dir=self.out)
        self.assertEqual(report["status"], "passed", report)

    def test_navigation_off_the_approved_origin_fails(self):
        report = self.run_script(
            {"action": "click", "selector": "#away"}, {"action": "wait_for", "selector": "#go"}
        )
        self.assertEqual(report["status"], "failed")
        errors = [step.get("error", "") for step in report["steps"]]
        self.assertTrue(any(e.startswith("off_origin_navigation") for e in errors), errors)

    def test_unapproved_origin_is_refused_before_launch(self):
        with self.assertRaises(ValueError):
            ui_eval.run(script(self.base), approved_origin="https://other.test", out_dir=self.out)
