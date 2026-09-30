import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import control


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / ".gitignore").write_text("artifacts/\n")
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.test",
                "commit",
                "-qm",
                "initial",
            ],
            cwd=self.root,
            check=True,
        )
        self.checks = [("sample", ".", [sys.executable, "-c", "print('verified')"])]
        self.suites_patch = patch.object(control, "SUITES", {"sample": self.checks})
        self.suites_patch.start()
        self.addCleanup(self.suites_patch.stop)

    def verify(self, **kwargs):
        return control.verify("sample", root=self.root, **kwargs)

    def test_builtin_contracts_and_conservative_registry_approvals(self):
        self.assertEqual(
            control.BUILTIN_SUITES["stack"][1],
            ("stack-lint", ".", [sys.executable, "tools/sstack/lint.py", "--code-only"]),
        )
        self.assertEqual(
            control.BUILTIN_SUITES["docs"][0][2],
            [sys.executable, "tools/sstack/check_contracts.py", "--include-readme"],
        )
        path = self.root / control.registry.REGISTRY_PATH
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "suites": {
                        "custom": [
                            {"name": "serial"},
                            {"name": "safe", "parallel_safe": True},
                            {"name": "reusable", "reuse_safe": True},
                        ]
                    }
                }
            )
        )
        self.assertEqual(
            control.approved_checks(self.root, "parallel_safe"),
            {"stack", "stack-lint", "docs", "safe"},
        )
        self.assertEqual(
            control.approved_checks(self.root, "reuse_safe"),
            {"stack", "stack-lint", "docs", "reusable"},
        )

    def test_run_directory_output_is_rebound_and_never_reused(self):
        self.checks[:] = [
            (
                "sample",
                ".",
                [
                    sys.executable,
                    "-c",
                    "import sys; from pathlib import Path; Path(sys.argv[1]).write_text('fresh')",
                    control.RUN_DIR + "/result.json",
                ],
            )
        ]
        report = self.cached()
        original = Path(report["checks"][0]["command"][-1])
        self.assertEqual(original.read_text(), "fresh")
        original.unlink()
        result = self.reuse(report)
        self.assertEqual(result["reuse"]["status"], "miss")
        self.assertEqual(result["reuse"]["reason"], "run_directory_outputs_not_reusable")
        self.assertEqual(result["status"], "passed")
        output = Path(result["checks"][0]["command"][-1])
        self.assertNotEqual(original, output)
        self.assertEqual(output.parent, (self.root / result["report"]).parent.resolve())
        self.assertEqual(output.read_text(), "fresh")
        self.assertEqual(
            result["checks"][0]["command"],
            control.bind_run_dir(self.checks[0][2], self.root, result["checks"][0]["log"]),
        )

    def test_all_runs_shared_docs_check_once(self):
        with patch.object(control, "SUITES", control.BUILTIN_SUITES):
            result = control.verify("all", plan=True, root=self.root)
        self.assertEqual(
            [check["name"] for check in result["checks"]], ["stack", "stack-lint", "docs"]
        )

    def test_parallel_checks_overlap_but_serial_check_is_a_barrier(self):
        names = ["first", "second", "serial", "third", "fourth"]
        self.checks[:] = [(name, ".", [sys.executable, "-c", "pass"]) for name in names]
        intervals = {}
        lock = threading.Lock()
        rendezvous = threading.Barrier(2)

        def execute(name, cwd, command, **kwargs):
            with lock:
                intervals[name] = [time.monotonic()]
            if name != "serial":
                rendezvous.wait(timeout=5)
            time.sleep(0.02)
            with lock:
                intervals[name].append(time.monotonic())
            return {
                "name": name,
                "cwd": cwd,
                "command": command,
                "status": "passed",
                "exit_code": 0,
                "duration_seconds": intervals[name][1] - intervals[name][0],
            }, name

        with (
            patch.object(control, "approved_checks", return_value=set(names) - {"serial"}),
            patch.object(control, "run_check", side_effect=execute),
        ):
            report = self.verify(jobs=2)
        self.assertEqual([check["name"] for check in report["checks"]], names)
        for left, right in [("first", "second"), ("third", "fourth")]:
            self.assertLess(
                max(intervals[left][0], intervals[right][0]),
                min(intervals[left][1], intervals[right][1]),
            )
        self.assertLessEqual(max(intervals[name][1] for name in names[:2]), intervals["serial"][0])
        self.assertLessEqual(intervals["serial"][1], min(intervals[name][0] for name in names[3:]))
        self.assertGreater(report["elapsed_seconds"], 0)

    def test_jobs_bounds_and_default_custom_serial_execution(self):
        for jobs in (0, 9, True):
            with self.assertRaises(ValueError):
                self.verify(jobs=jobs)
        self.checks.clear()
        self.checks.extend((name, ".", [sys.executable, "-c", "pass"]) for name in ("a", "b"))
        active = threading.Lock()

        def execute(name, cwd, command, **kwargs):
            self.assertTrue(active.acquire(blocking=False), "custom checks overlapped")
            time.sleep(0.02)
            active.release()
            return {
                "name": name,
                "cwd": cwd,
                "command": command,
                "status": "passed",
                "exit_code": 0,
                "duration_seconds": 0.02,
            }, "ok"

        with patch.object(control, "run_check", side_effect=execute):
            self.assertEqual(self.verify(jobs=8)["status"], "passed")

    def test_parallel_work_never_exceeds_job_limit(self):
        self.checks[:] = [(str(index), ".", [sys.executable, "-c", "pass"]) for index in range(6)]
        lock = threading.Lock()
        active = 0
        maximum = 0

        def execute(name, cwd, command, **kwargs):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            return {
                "name": name,
                "cwd": cwd,
                "command": command,
                "status": "passed",
                "exit_code": 0,
                "duration_seconds": 0.02,
            }, "ok"

        with (
            patch.object(
                control, "approved_checks", return_value={check[0] for check in self.checks}
            ),
            patch.object(control, "run_check", side_effect=execute),
        ):
            self.assertEqual(self.verify(jobs=2)["status"], "passed")
        self.assertEqual(maximum, 2)

    def test_runtime_identity_tracks_distribution_python_and_executable_changes(self):
        executable = self.root / "runner"
        executable.write_text("#!/bin/sh\necho first\n")
        executable.chmod(0o755)
        checks = [("local", ".", ["./runner"])]
        original = control.runtime_identity(checks, self.root)
        self.assertEqual(original["executables"][0]["path"], str(executable.resolve()))
        executable.write_text("#!/bin/sh\necho changed\n")
        self.assertNotEqual(original, control.runtime_identity(checks, self.root))
        original = control.runtime_identity(checks, self.root)
        with patch.object(control.importlib.metadata, "distributions", return_value=[]):
            self.assertNotEqual(original, control.runtime_identity(checks, self.root))
        with patch.object(control.sys, "version", "different Python"):
            self.assertNotEqual(original, control.runtime_identity(checks, self.root))

    def test_parallel_failure_timeout_and_missing_check_are_not_hidden(self):
        self.checks[:] = [
            ("fails", ".", [sys.executable, "-c", "raise SystemExit(7)"]),
            ("times-out", ".", [sys.executable, "-c", "import time; time.sleep(30)"]),
            ("missing", ".", [str(self.root / "missing")]),
            ("passes", ".", [sys.executable, "-c", "print('last')"]),
        ]
        with patch.object(
            control, "approved_checks", return_value={check[0] for check in self.checks}
        ):
            report = self.verify(jobs=2, timeout=0.2)
        self.assertEqual(
            [check["status"] for check in report["checks"]],
            ["failed", "timeout", "blocked", "passed"],
        )
        self.assertEqual(report["status"], "failed")
        self.assertTrue(all(check["duration_seconds"] >= 0 for check in report["checks"]))

    def cached(self):
        return self.verify(environment_key="immutable-fixture-v1", base="HEAD")

    def reuse(self, report, **kwargs):
        arguments = {
            "reuse": report["report"],
            "environment_key": "immutable-fixture-v1",
            "base": "HEAD",
        }
        arguments.update(kwargs)
        with patch.object(control, "approved_checks", return_value={"sample"}):
            return self.verify(**arguments)

    def test_exact_reuse_returns_original_report_without_running_or_writing(self):
        report = self.cached()
        before = set((self.root / "artifacts/sstack").iterdir())
        with patch.object(control, "run_check") as run:
            reused = self.reuse(report)
        run.assert_not_called()
        self.assertEqual(reused["report"], report["report"])
        self.assertEqual(reused["reuse"]["status"], "hit")
        self.assertEqual(set((self.root / "artifacts/sstack").iterdir()), before)
        self.assertEqual(json.loads((self.root / report["report"]).read_text()), report)
        self.assertNotIn("immutable-fixture-v1", json.dumps(report))

    def test_reuse_requires_key_and_custom_opt_in(self):
        report = self.cached()
        with self.assertRaises(ValueError):
            self.verify(reuse=report["report"])
        result = self.verify(
            reuse=report["report"], environment_key="immutable-fixture-v1", base="HEAD"
        )
        self.assertEqual(result["reuse"]["status"], "miss")
        self.assertEqual(result["status"], "passed")

    def test_changed_key_environment_source_base_command_or_log_reruns(self):
        for change in ("key", "runtime", "source", "base", "command", "cwd", "log", "head"):
            with self.subTest(change=change):
                report = self.cached()
                kwargs = {}
                environment = patch.dict(os.environ, {}, clear=False)
                if change == "key":
                    kwargs["environment_key"] = "new-fixture"
                elif change == "runtime":
                    environment = patch.dict(os.environ, {"SSTACK_TEST_RUNTIME": "changed"})
                elif change == "source":
                    (self.root / "new-input.txt").write_text("changed")
                elif change == "base":
                    kwargs["base"] = None
                elif change == "command":
                    self.checks[0] = ("sample", ".", [sys.executable, "-c", "print('different')"])
                elif change == "cwd":
                    self.checks[0] = ("sample", "./", self.checks[0][2])
                elif change == "log":
                    (self.root / report["checks"][0]["log"]).write_text("tampered")
                elif change == "head":
                    subprocess.run(
                        [
                            "git",
                            "-c",
                            "user.name=Test",
                            "-c",
                            "user.email=test@example.test",
                            "commit",
                            "--allow-empty",
                            "-qm",
                            "new head",
                        ],
                        cwd=self.root,
                        check=True,
                    )
                with environment:
                    result = self.reuse(report, **kwargs)
                self.assertEqual(result["reuse"]["status"], "miss")
                self.assertNotEqual(result["report"], report["report"])
                self.assertEqual(result["status"], "passed")

    def test_failed_live_ui_and_invalid_reports_never_reuse(self):
        report = self.cached()
        report_path = self.root / report["report"]
        for changes in (
            {"status": "failed"},
            {"scope": "live"},
            {"ui": "passed"},
            {"live_kizen": "passed"},
            {"sources_changed_during_run": True},
            {"fingerprint_policy": {}},
            {"source_fingerprint_after": "different"},
            {"checks": []},
            {"checks": [{"status": "passed"}]},
            {"runtime_identity": {}},
            {"git_revision": None},
        ):
            with self.subTest(changes=changes):
                report_path.write_text(json.dumps({**report, **changes}))
                self.assertEqual(self.reuse(report)["reuse"]["status"], "miss")
        for data in ("not JSON", "[]", "null"):
            report_path.write_text(data)
            self.assertEqual(self.reuse(report)["reuse"]["status"], "miss")
        report_path.unlink()
        self.assertEqual(self.reuse(report)["reuse"]["status"], "miss")


if __name__ == "__main__":
    unittest.main()
