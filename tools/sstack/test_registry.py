import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import control
import registry


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "test")
        self.git("config", "user.email", "test@example.invalid")
        self.write(".gitignore", "artifacts/\n")
        self.write("app/main.py", "value = 1\n")
        self.write("remote/README.md", "Check deployed acceptance.\n")
        projects = [
            {"id": "app", "paths": ["app/"], "suites": ["stack"], "external": [], "affects": []},
            {
                "id": "remote",
                "paths": ["remote/"],
                "suites": [],
                "external": ["remote/README.md"],
                "affects": [],
            },
            {
                "id": "shared",
                "paths": ["tools/", ".gitignore"],
                "suites": ["stack"],
                "external": [],
                "affects": ["app", "remote"],
            },
        ]
        self.write(registry.REGISTRY_PATH, json.dumps({"version": 1, "projects": projects}))
        self.git("add", ".")
        self.git("commit", "-qm", "baseline")
        self.base = registry.revision(self.root, "HEAD")

    def git(self, *args):
        return registry.git(self.root, *args)

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)

    def test_committed_staged_unstaged_untracked_deleted_changes_are_selected(self):
        self.write("app/committed.py", "x = 1")
        self.git("add", "app/committed.py")
        self.git("commit", "-qm", "new implementation")
        self.write("app/staged.py", "x = 2")
        self.git("add", "app/staged.py")
        self.write("app/untracked.toml", "x = 3")
        (self.root / "app/main.py").unlink()
        result = control.coverage(self.root, self.base)
        self.assertEqual(
            set(result["files"]),
            {"app/committed.py", "app/staged.py", "app/untracked.toml", "app/main.py"},
        )
        self.assertEqual(result["projects"], ["app"])
        self.assertEqual(result["suites"], ["stack"])
        self.assertEqual(result["base"], self.base)

    def test_unknown_project_is_blocked(self):
        self.write("new-project/test_failing.py", "assert False")
        result = control.coverage(self.root, self.base)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["unknown_paths"], ["new-project/test_failing.py"])
        report = control.verify("changed", base=self.base, root=self.root)
        self.assertEqual(report["status"], "blocked")

    def test_shared_change_includes_dependents_and_external_proof(self):
        self.write("tools/shared.py", "x = 1")
        result = control.coverage(self.root, self.base)
        self.assertEqual(result["projects"], ["app", "remote", "shared"])
        self.assertEqual(result["external_checks"][0]["project"], "remote")

    def test_external_only_is_blocked_and_never_invokes_remote_code(self):
        self.write("remote/deploy.py", "raise RuntimeError('do not execute')")
        with patch.object(control, "run_check") as run:
            report = control.verify("changed", base=self.base, root=self.root)
        run.assert_not_called()
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["checks"][0]["reason"], "external_acceptance_not_run")
        self.assertEqual(report["base_revision"], self.base)

    def test_staged_change_reverted_in_worktree_still_requires_checks(self):
        self.write("app/main.py", "value = 2\n")
        self.git("add", "app/main.py")
        self.write("app/main.py", "value = 1\n")
        self.assertIn("app/main.py", control.coverage(self.root, self.base)["files"])

    def test_plan_includes_coverage_without_writing_evidence(self):
        self.write("app/new.py", "x = 1")
        report = control.verify("changed", base=self.base, root=self.root, plan=True)
        self.assertEqual(report["coverage"]["projects"], ["app"])
        self.assertFalse((self.root / "artifacts").exists())

    def test_invalid_base_or_registry_fails_closed(self):
        with self.assertRaises(subprocess.CalledProcessError):
            control.coverage(self.root, "does-not-exist")
        self.write(registry.REGISTRY_PATH, json.dumps({"version": 1, "projects": []}))
        with self.assertRaises(ValueError):
            control.coverage(self.root, self.base)

    def test_registered_custom_suite_is_selected_and_executed(self):
        path = self.root / registry.REGISTRY_PATH
        document = json.loads(path.read_text())
        document["suites"] = {
            "app": [{"name": "app-tests", "cwd": "app", "command": ["$PYTHON", "checks.py"]}]
        }
        document["projects"][0]["suites"] = ["app"]
        path.write_text(json.dumps(document))
        self.write("app/checks.py", "print('verified custom project')\n")
        self.git("add", ".")
        self.git("commit", "-qm", "register custom project")
        base = registry.revision(self.root, "HEAD")
        self.write("app/main.py", "value = 2\n")
        report = control.verify("changed", base=base, root=self.root)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["coverage"]["suites"], ["app"])
        self.assertEqual(report["checks"][0]["name"], "app-tests")
        self.assertEqual(report["checks"][0]["command"][0], control.sys.executable)
        self.assertEqual(control.doctor(self.root, "app")["status"], "passed")

    def test_invalid_suite_contracts_fail_closed(self):
        path = self.root / registry.REGISTRY_PATH
        original = json.loads(path.read_text())
        bad_suites = [
            {"stack": [{"name": "override", "cwd": ".", "command": ["true"]}]},
            {"custom": [{"name": "../escape", "cwd": ".", "command": ["true"]}]},
            {"custom": [{"name": "check", "cwd": "../escape", "command": ["true"]}]},
            {"custom": [{"name": "check", "cwd": ".", "command": "echo unsafe"}]},
            {"custom": []},
        ]
        for suites in bad_suites:
            with self.subTest(suites=suites):
                path.write_text(json.dumps({**original, "suites": suites}))
                with self.assertRaises(ValueError):
                    control.coverage(self.root, self.base)

    def test_custom_safety_flags_require_booleans_and_preserve_check_shape(self):
        path = self.root / registry.REGISTRY_PATH
        document = json.loads(path.read_text())
        check = {"name": "custom-check", "cwd": ".", "command": ["$PYTHON", "checks.py"]}
        for flag in ("parallel_safe", "reuse_safe"):
            for value in (False, True, None, "true", 1, [], {}):
                with self.subTest(flag=flag, value=value):
                    document["suites"] = {"custom": [{**check, flag: value}]}
                    path.write_text(json.dumps(document))
                    if isinstance(value, bool):
                        loaded = registry.load_suites(self.root, {})["custom"][0]
                        self.assertEqual(
                            loaded, ("custom-check", ".", [control.sys.executable, "checks.py"])
                        )
                    else:
                        with self.assertRaisesRegex(ValueError, flag):
                            registry.load_suites(self.root, {})

    def register(self, **fields):
        path = self.root / registry.REGISTRY_PATH
        document = json.loads(path.read_text())
        check = {"name": "app-tests", "cwd": "app", "command": ["$PYTHON", "checks.py"]}
        document["suites"] = {"app": [{**check, **fields}]}
        document["projects"][0]["suites"] = ["app"]
        path.write_text(json.dumps(document))

    def test_custom_run_dir_command_is_valid_and_bound_by_verify(self):
        script = "import sys; open(sys.argv[1], 'w').write('fresh')"
        self.register(command=["$PYTHON", "-c", script, control.RUN_DIR + "/app.json"])
        self.git("add", ".")
        self.git("commit", "-qm", "register run directory check")
        base = registry.revision(self.root, "HEAD")
        self.write("app/main.py", "value = 2\n")
        report = control.verify("changed", base=base, root=self.root)
        self.assertEqual(report["status"], "passed")
        check = report["checks"][0]
        run_dir = (self.root / report["report"]).parent.resolve()
        self.assertEqual(check["command"][-1], str(run_dir / "app.json"))
        self.assertEqual((run_dir / "app.json").read_text(), "fresh")
        registered = control.suites_for(self.root)["app"][0][2]
        self.assertEqual(
            check["command"], control.bind_run_dir(registered, self.root, check["log"])
        )

    def test_min_python_and_requires_are_optional_readiness_contracts(self):
        self.write("app/checks.py", "print('verified')\n")
        current = "{}.{}".format(*control.sys.version_info[:2])
        self.register(min_python=current, requires=["checks.py", "."])
        self.assertEqual(
            registry.load_suites(self.root, {})["app"],
            [("app-tests", "app", [control.sys.executable, "checks.py"])],
        )
        self.assertEqual(control.doctor(self.root, "app")["status"], "passed")
        self.register(min_python="99.0", requires=["checks.py", "fixtures/", "data/seed.json"])
        (result,) = control.readiness(self.root, "app")["app"]
        self.assertEqual(
            result["reasons"],
            [
                "python_99_0_required",
                "required_path_missing:fixtures/",
                "required_path_missing:data/seed.json",
            ],
        )
        self.assertEqual(control.doctor(self.root, "app")["status"], "blocked")
        report = control.verify("app", root=self.root)
        self.assertEqual((report["status"], report["checks"][0]["status"]), ("blocked", "blocked"))
        self.write("app/fixtures/case.json", "{}")
        self.write("app/data/seed.json", "{}")
        with patch.object(control.sys, "version_info", (99, 0, 0, "final", 0)):
            self.assertEqual(control.doctor(self.root, "app")["status"], "passed")

    def test_invalid_min_python_and_requires_fail_closed(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        (self.root / "app/outside").symlink_to(outside.name, target_is_directory=True)
        for fields in (
            *({"min_python": value} for value in (3.12, "3", "3.12.1", "v3.12", "", None, [3])),
            *(
                {"requires": value}
                for value in (
                    [],
                    "checks.py",
                    None,
                    [""],
                    [1],
                    ["/etc/hosts"],
                    ["../app/main.py"],
                    ["tests/../../main.py"],
                    ["nul\0byte"],
                    ["outside/secret"],
                )
            ),
        ):
            with self.subTest(fields=fields):
                self.register(**fields)
                with self.assertRaisesRegex(ValueError, "min_python|require"):
                    registry.load_suites(self.root, {})

    def test_excluded_unowned_changes_still_block(self):
        path = self.root / registry.REGISTRY_PATH
        document = json.loads(path.read_text())
        document["projects"][0]["exclude_paths"] = ["app/private/"]
        path.write_text(json.dumps(document))
        self.git("add", ".")
        self.git("commit", "-qm", "exclude private paths")
        self.write("app/private/new.py", "value = 1\n")
        result = control.coverage(self.root, "HEAD")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["unknown_paths"], ["app/private/new.py"])

    def test_invalid_exclude_paths_fail_closed(self):
        path = self.root / registry.REGISTRY_PATH
        document = json.loads(path.read_text())
        for excludes in (None, "app/", [""], [1], ["/app/"], ["../app/"], ["."]):
            with self.subTest(excludes=excludes):
                document["projects"][0]["exclude_paths"] = excludes
                path.write_text(json.dumps(document))
                with self.assertRaises(ValueError):
                    control.coverage(self.root, self.base)

    def test_default_registry_keeps_lightweight_selection_exact(self):
        document = json.loads((Path(__file__).parent / "projects.json").read_text())
        if document["suites"] or {item["id"] for item in document["projects"]} != {
            "stack",
            "repository",
            "documentation",
        }:
            self.skipTest("installed registry is customized; verify checks its coverage")
        self.write(registry.REGISTRY_PATH, json.dumps(document))
        # Supply the docs builtin explicitly so this test exercises registry policy.
        suites = {"stack": [], "docs": []}
        cases = [
            (["README.md"], ["docs"], []),
            (["tools/sstack/README.md"], ["docs"], []),
            (["tools/sstack/skills/sstack/SKILL.md"], ["stack"], []),
            (["AGENTS.md"], ["stack"], []),
            (["CLAUDE.md"], ["stack"], []),
            (["install.py"], ["stack"], []),
            ([".sstack.json"], ["stack"], []),
            ([".github/workflows/sstack-quality.yml"], ["stack"], []),
            (["tools/sstack/control.py"], ["stack"], []),
            (["README.md", "tools/sstack/control.py"], ["docs", "stack"], []),
            (["README.md", "other/README.md"], ["docs"], ["other/README.md"]),
            (["tools/sstack/README.md.backup"], ["stack"], []),
        ]
        for files, expected, unknown in cases:
            with (
                self.subTest(files=files),
                patch.object(registry, "changed_files", return_value=files),
            ):
                result = registry.coverage(self.root, self.base, suites)
                self.assertEqual(result["suites"], expected)
                self.assertEqual(result["unknown_paths"], unknown)
                self.assertEqual(result["status"], "blocked" if unknown else "passed")

    def test_default_root_suites_are_refreshed_after_registration(self):
        path = self.root / registry.REGISTRY_PATH
        document = json.loads(path.read_text())
        with patch.object(control, "ROOT", self.root):
            self.assertNotIn("new-project", control.suites_for(self.root))
            document["suites"] = {
                "new-project": [
                    {"name": "new-tests", "cwd": "app", "command": ["$PYTHON", "checks.py"]}
                ]
            }
            path.write_text(json.dumps(document))
            self.assertEqual(control.suites_for(self.root)["new-project"][0][0], "new-tests")
            document["suites"]["new-project"][0]["command"][-1] = "updated.py"
            path.write_text(json.dumps(document))
            self.assertEqual(control.suites_for(self.root)["new-project"][0][2][-1], "updated.py")


if __name__ == "__main__":
    unittest.main()
