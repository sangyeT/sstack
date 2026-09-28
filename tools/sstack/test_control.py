import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import control


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / ".gitignore").write_text("artifacts/\n")

    def run_python(self, code, timeout=5):
        return control.run_check(
            "sample", ".", [sys.executable, "-c", code], root=self.root, timeout=timeout
        )

    def test_nonzero_is_failed_and_output_retained(self):
        result, log = self.run_python("print('diagnostic'); raise SystemExit(7)")
        self.assertEqual((result["status"], result["exit_code"]), ("failed", 7))
        self.assertIn("diagnostic", log)

    def test_missing_executable_is_blocked(self):
        result, _ = control.run_check(
            "missing", ".", [str(self.root / "missing")], root=self.root, timeout=1
        )
        self.assertEqual(result["status"], "blocked")

    def test_timeout_is_not_success(self):
        result, log = self.run_python("import time; time.sleep(30)", timeout=0.1)
        self.assertEqual(result["status"], "timeout")
        self.assertIn("Timed out", log)

    def test_doctor_includes_untracked_without_echoing_contents(self):
        (self.root / "untracked.md").write_text("<<<<<<< private-content\n")
        result = control.doctor(self.root)
        self.assertEqual(result["conflicts"], [{"path": "untracked.md", "line": 1}])
        self.assertNotIn("private-content", json.dumps(result))

    def test_plan_does_not_run_or_write(self):
        with patch.object(control, "run_check") as run:
            result = control.verify("all", plan=True, root=self.root)
        run.assert_not_called()
        self.assertEqual(result["status"], "planned")
        self.assertFalse((self.root / "artifacts").exists())

    def test_failure_does_not_hide_later_checks_and_report_persists(self):
        checks = {
            "sample": [
                ("fails", ".", [sys.executable, "-c", "raise SystemExit(7)"]),
                ("passes", ".", [sys.executable, "-c", "print('later')"]),
            ]
        }
        with patch.object(control, "SUITES", checks):
            report = control.verify("sample", root=self.root)
        self.assertEqual([item["status"] for item in report["checks"]], ["failed", "passed"])
        self.assertEqual(json.loads((self.root / report["report"]).read_text()), report)
        self.assertIn("later", (self.root / report["checks"][1]["log"]).read_text())

    def test_zero_discovered_tests_is_blocked(self):
        result, _ = control.run_check(
            "empty", ".", [sys.executable, "-m", "unittest", "discover"], root=self.root, timeout=5
        )
        self.assertEqual(result["status"], "blocked")

    def test_absent_suites_block_doctor_and_are_not_silently_omitted(self):
        with patch.object(control, "run_check") as run:
            report = control.verify("all", root=self.root)
        run.assert_not_called()
        self.assertEqual(len(report["checks"]), 1)
        self.assertEqual({item["status"] for item in report["checks"]}, {"blocked"})
        self.assertEqual(report["status"], "blocked")
        diagnostics = control.doctor(self.root)
        self.assertEqual(diagnostics["status"], "blocked")
        self.assertEqual(diagnostics["verification"], "not_run")
        self.assertEqual(set(diagnostics["readiness"]), {"stack"})

    def test_stack_missing_dev_dependencies_blocks_before_execution(self):
        with patch.object(control.importlib.util, "find_spec", return_value=None):
            result = control.readiness(self.root, "stack")["stack"][0]
        self.assertIn("dev_dependency_missing:ruff", result["reasons"])
        self.assertIn("dev_dependency_missing:yaml", result["reasons"])
        self.assertEqual(result["status"], "blocked")

    def test_doctor_can_target_one_ready_suite(self):
        tests = self.root / "tools/sstack"
        tests.mkdir(parents=True)
        (tests / "test_example.py").write_text("import unittest")
        self.assertEqual(control.doctor(self.root, "stack")["status"], "passed")

    def test_empty_test_directory_is_blocked(self):
        (self.root / "tools/sstack").mkdir(parents=True)
        result = control.readiness(self.root, "stack")["stack"][0]
        self.assertIn("no_test_files", result["reasons"])

    def test_npm_scripts_are_checked_not_just_manifest_presence(self):
        (self.root / "package.json").write_text(json.dumps({"scripts": {"lint": "echo ok"}}))
        checks = {
            "web": [
                ("web-" + step, ".", ["npm", "run", step]) for step in ("lint", "test", "build")
            ]
        }
        with (
            patch.object(control.shutil, "which", return_value="/bin/tool"),
            patch.object(control, "SUITES", checks),
        ):
            lint, tests, build = control.readiness(self.root, "web")["web"]
        self.assertEqual(lint["status"], "ready")
        self.assertIn("npm_script_missing", tests["reasons"])
        self.assertIn("npm_script_missing", build["reasons"])
        (self.root / "package.json").write_text("invalid")
        with patch.object(control, "SUITES", checks):
            self.assertIn(
                "package_json_invalid", control.readiness(self.root, "web")["web"][0]["reasons"]
            )

    def test_blocked_check_does_not_prevent_ready_checks(self):
        checks = {
            "sample": [
                ("missing", "missing-directory", [sys.executable, "-c", "raise SystemExit(9)"]),
                ("passes", ".", [sys.executable, "-c", "print('later')"]),
            ]
        }
        with patch.object(control, "SUITES", checks):
            report = control.verify("sample", root=self.root)
        self.assertEqual([item["status"] for item in report["checks"]], ["blocked", "passed"])
        self.assertEqual(report["status"], "blocked")

    def test_mutated_sources_invalidate_success(self):
        checks = {
            "sample": [
                (
                    "mutate",
                    ".",
                    [
                        sys.executable,
                        "-c",
                        "from pathlib import Path; Path('changed.py').write_text('x = 1')",
                    ],
                )
            ]
        }
        with patch.object(control, "SUITES", checks):
            report = control.verify("sample", root=self.root)
        self.assertEqual(report["status"], "blocked")
        self.assertTrue(report["sources_changed_during_run"])

    def test_fingerprint_includes_toml_binary_large_files_and_executable_mode(self):
        config = self.root / "pyproject.toml"
        config.write_text("enabled = true")
        first = control.fingerprint(self.root)
        config.write_text("enabled = false")
        second = control.fingerprint(self.root)
        self.assertNotEqual(first, second)
        large = self.root / "large.bin"
        large.write_bytes(b"\0" * 2_100_000)
        third = control.fingerprint(self.root)
        self.assertNotEqual(second, third)
        with large.open("r+b") as stream:
            stream.seek(2_050_000)
            stream.write(b"changed")
        self.assertNotEqual(third, control.fingerprint(self.root))
        previous = control.fingerprint(self.root)
        config.chmod(0o755)
        self.assertNotEqual(previous, control.fingerprint(self.root))

    def test_fingerprint_symlink_target_contents_and_deleted_tracked_file(self):
        target = self.root / "target.toml"
        target.write_text("x = 1")
        link = self.root / "linked.toml"
        link.symlink_to("target.toml")
        first = control.fingerprint(self.root)
        target.write_text("x = 2")
        self.assertNotEqual(first, control.fingerprint(self.root))
        linked_record = control.input_record(self.root.resolve(), link)
        self.assertEqual(linked_record["content"]["sha256"], control.file_digest(target))
        subprocess.run(["git", "add", "target.toml"], cwd=self.root, check=True)
        before_delete = control.fingerprint(self.root)
        target.unlink()
        self.assertNotEqual(before_delete, control.fingerprint(self.root))
        self.assertEqual(control.input_record(self.root, target)["type"], "missing")

    def test_fingerprint_exclusions_are_explicit_and_doctor_avoids_secrets_and_binaries(self):
        secret = self.root / ".env"
        secret.write_text("<<<<<<< private-value")
        (self.root / "binary.py").write_bytes(b"x" * 2_100_000)
        link = self.root / "alias.txt"
        link.symlink_to(".env")
        before = control.fingerprint(self.root)
        secret.write_text("<<<<<<< other-private-value")
        self.assertEqual(before, control.fingerprint(self.root))
        self.assertEqual(control.doctor(self.root)["conflicts"], [])
        self.assertIn(
            {"path": ".env", "reason": "runtime_or_credentials_file"},
            control.excluded_inputs(self.root),
        )
        self.assertNotIn(
            "private-value", json.dumps(control.input_record(self.root.resolve(), link))
        )

    def test_external_symlink_fails_without_reading_target(self):
        (self.root / "external.txt").symlink_to(self.root.parent / "not-in-repository")
        with self.assertRaises(ValueError):
            control.fingerprint(self.root)

    def test_report_attests_log_digest(self):
        checks = {"sample": [("pass", ".", [sys.executable, "-c", "print('ok')"])]}
        with patch.object(control, "SUITES", checks):
            report = control.verify("sample", root=self.root)
        result = report["checks"][0]
        self.assertEqual(result["log_sha256"], control.file_digest(self.root / result["log"]))
        self.assertEqual(report["fingerprint_policy"]["version"], 2)


if __name__ == "__main__":
    unittest.main()
