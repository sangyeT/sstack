"""Contract checks must catch broken wiring without inspecting project data."""

import tempfile
import unittest
from pathlib import Path

from check_contracts import SKILLS, STACK, check


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name in SKILLS:
            skill = self.root / STACK / "skills" / name
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: Useful guidance.\n---\n# Skill\n"
            )
            for host in (".agents", ".claude"):
                registration = self.root / host / "skills" / name
                registration.parent.mkdir(parents=True, exist_ok=True)
                registration.symlink_to(Path("../../") / STACK / "skills" / name)
        for path in ("AGENTS.md", "CLAUDE.md", str(STACK / "README.md")):
            (self.root / path).write_text("# Instructions\n")

    def codes(self):
        return [finding.code for finding in check(self.root)]

    def test_valid_portable_setup(self):
        (self.root / STACK / "README.md").write_text(
            "[PM](skills/sstack/SKILL.md#heading)\n"
            "[Root](/AGENTS.md)\n[web](https://example.invalid/nope)\n"
            "[anchor](#missing-anchor)\n"
            "```markdown\n[example](missing.md)\n```\n"
            "`[inline example](missing.md)`\n"
        )
        self.assertEqual(check(self.root), [])

    def test_broken_local_link_has_location_without_source(self):
        (self.root / STACK / "README.md").write_text("# Intro\n[private words](missing.md)\n")
        finding = check(self.root)[0]
        self.assertEqual((finding.code, finding.line), ("LINK001", 2))
        self.assertEqual(finding.path, "tools/sstack/README.md")
        self.assertNotIn("private words", str(finding))

    def test_malformed_and_duplicate_yaml_are_rejected(self):
        skill = self.root / STACK / "skills/sstack/SKILL.md"
        for frontmatter in (
            "name: [invalid",
            "name: sstack\nname: sstack\ndescription: valid",
            "name: sstack\ndescription: valid\nmetadata:\n  a: 1\n  a: 2",
        ):
            with self.subTest(frontmatter=frontmatter):
                skill.write_text(f"---\n{frontmatter}\n---\n")
                self.assertIn("SKILL002", self.codes())

    def test_name_and_description_must_be_valid(self):
        skill = self.root / STACK / "skills/sstack/SKILL.md"
        skill.write_text("---\nname: wrong\ndescription: ' '\n---\n")
        self.assertEqual(self.codes(), ["SKILL003", "SKILL004"])

    def test_broken_or_wrong_registration_fails(self):
        registration = self.root / ".claude/skills/sstack"
        registration.unlink()
        for target in ("missing", "../../tools/sstack/skills/sstack-mode"):
            with self.subTest(target=target):
                registration.symlink_to(target)
                self.assertEqual(self.codes(), ["REGISTER001"])
                registration.unlink()

    def test_document_hygiene(self):
        (self.root / "AGENTS.md").write_text("# Title  \n<<<<<<< HEAD\nlast line")
        self.assertEqual(set(self.codes()), {"TEXT001", "TEXT002", "TEXT003"})

    def test_encoded_spaces_and_parentheses_in_links(self):
        (self.root / STACK / "a file (copy).md").write_text("# Target\n")
        (self.root / STACK / "README.md").write_text(
            '[target](<a file (copy).md> "title")\n[target](a%20file%20(copy).md)\n'
        )
        self.assertEqual(check(self.root), [])

    def test_history_and_unrelated_projects_are_out_of_scope(self):
        history = self.root / STACK / "skills/sstack/history"
        history.mkdir()
        (history / "old.md").write_text("[old](missing.md)  ")
        unrelated = self.root / "other-project"
        unrelated.mkdir()
        (unrelated / "SKILL.md").write_text("invalid and outside scope")
        self.assertEqual(check(self.root), [])


if __name__ == "__main__":
    unittest.main()
