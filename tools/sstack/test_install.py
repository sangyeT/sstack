import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "sstack_install", Path(__file__).resolve().parents[2] / "install.py"
)
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "source"
        self.target = Path(self.temp.name) / "target"
        for root in (self.source, self.target):
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
        for skill in installer.SKILLS:
            path = self.source / "tools/sstack/skills" / skill / "SKILL.md"
            path.parent.mkdir(parents=True)
            path.write_text(f"# {skill}\n")
        (self.source / "tools/sstack/control.py").write_text("print('control')\n")
        (self.source / "install.py").write_text("print('installer')\n")
        subprocess.run(["git", "-C", str(self.source), "add", "."], check=True)
        (self.source / "tools/sstack/untracked-secret.txt").write_text("private")
        (self.target / "AGENTS.md").write_text("# User instructions\n")

    def install(self, **kwargs):
        return installer.install(self.target, source=self.source, **kwargs)

    def test_install_preserves_instructions_and_rerun_is_noop(self):
        result = self.install(board_url="https://boards.test/projects/PM", project_key="PM")
        self.assertEqual(len(result["links"]), 2 * len(installer.SKILLS))
        self.assertTrue((self.target / ".claude/skills/sstack/SKILL.md").is_file())
        self.assertTrue((self.target / "AGENTS.md").read_text().startswith("# User instructions\n"))
        self.assertFalse((self.target / "tools/sstack/untracked-secret.txt").exists())
        result = self.install()
        self.assertEqual(result["files"], [])
        self.assertEqual(result["links"], [])
        self.assertEqual((self.target / "AGENTS.md").read_text().count(installer.START), 1)

    def test_generated_evidence_is_ignored_and_existing_patterns_preserved(self):
        (self.target / ".gitignore").write_text("private-inputs/\n")
        self.install()
        evidence = self.target / "artifacts/sstack/run/report.json"
        evidence.parent.mkdir(parents=True)
        evidence.write_text("{}")
        untracked = subprocess.run(
            ["git", "-C", str(self.target), "ls-files", "--others", "--exclude-standard"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertNotIn("artifacts/sstack/", untracked)
        self.assertTrue((self.target / ".gitignore").read_text().startswith("private-inputs/\n"))
        self.assertEqual(self.install()["files"], [])

    def test_plan_does_not_write(self):
        self.assertEqual(self.install(plan=True)["status"], "planned")
        self.assertFalse((self.target / "tools").exists())
        self.assertEqual((self.target / "AGENTS.md").read_text(), "# User instructions\n")

    def test_conflict_aborts_all_changes(self):
        path = self.target / ".claude/skills/sstack"
        path.mkdir(parents=True)
        (path / "SKILL.md").write_text("user skill")
        with self.assertRaises(ValueError):
            self.install(board_url="https://boards.test/")
        self.assertFalse((self.target / "tools").exists())
        self.assertFalse((self.target / ".sstack.json").exists())
        self.assertEqual((path / "SKILL.md").read_text(), "user skill")

    def test_modified_package_and_managed_instructions_are_preserved(self):
        self.install()
        script = self.target / "tools/sstack/control.py"
        script.write_text("local edit")
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual(script.read_text(), "local edit")
        script.write_bytes((self.source / "tools/sstack/control.py").read_bytes())
        agents = self.target / "AGENTS.md"
        agents.write_text(agents.read_text().replace("PM goals", "custom goals"))
        with self.assertRaises(ValueError):
            self.install()
        self.assertIn("custom goals", agents.read_text())

    def test_bad_config_aborts_before_install(self):
        (self.target / ".sstack.json").write_text("malformed")
        with self.assertRaises(ValueError):
            self.install(board_url="https://boards.test/")
        self.assertFalse((self.target / "tools").exists())

    def test_symlink_parent_and_non_repository_are_rejected(self):
        (self.target / "tools").symlink_to(self.source / "tools")
        with self.assertRaises(ValueError):
            self.install()
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
            installer.install(self.target / "missing", source=self.source)

    def test_same_source_only_changes_board_when_requested(self):
        result = installer.install(self.source, source=self.source)
        self.assertEqual(result["files"], [])
        self.assertFalse((self.source / "AGENTS.md").exists())


if __name__ == "__main__":
    unittest.main()
