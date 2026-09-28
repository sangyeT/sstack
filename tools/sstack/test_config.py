import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import config


class BoardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def save(self, url="https://example.test/board/1?filter=&groupBy=none", scope=None):
        config.write_config(self.root, config.updated_config(self.root, url, "PM", scope))

    def test_unconfigured_show_blocks_without_writes(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(config.main(["show"], self.root), 1)
        self.assertEqual(json.loads(output.getvalue())["status"], "blocked")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_specific_scope_inherits_and_clear_restores_default(self):
        self.save()
        self.save("https://board.test/team", "apps")
        self.save("https://board.test/specific", "apps/one")
        self.assertEqual(config.select_board(self.root, "apps/one/src")["scope"], "apps/one")
        self.assertEqual(config.select_board(self.root, "apps/two")["scope"], "apps")
        self.assertEqual(config.select_board(self.root, "apps-other")["scope"], "default")
        config.write_config(
            self.root, config.updated_config(self.root, scope="apps/one", clear=True)
        )
        self.assertEqual(config.select_board(self.root, "apps/one")["scope"], "apps")

    def test_unsafe_urls_and_paths_rejected(self):
        for url in (
            "http://example.test/board",
            "https://user:pw@example.test/",
            "https://example.test/?token=private",
            "https://example.test/?api_key=private",
            "https://example.test/#secret",
            "https://example.test/a\nb",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                config.updated_config(self.root, url)
        for scope in ("/tmp", "../app", "apps/../other", "apps//one", "C:\\foo"):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                config.updated_config(self.root, "https://example.test", scope=scope)

    def test_malformed_configuration_is_preserved(self):
        path = self.root / ".sstack.json"
        for data in ('{"version":1,"version":1}', '{"version":2}', "not json"):
            path.write_text(data)
            with self.assertRaises(ValueError):
                self.save()
            self.assertEqual(path.read_text(), data)

    def test_symlink_configuration_or_scope_cannot_escape(self):
        external = self.root / "external.json"
        external.write_text("do not touch")
        (self.root / ".sstack.json").symlink_to(external)
        with self.assertRaises(ValueError):
            self.save()
        self.assertEqual(external.read_text(), "do not touch")
        (self.root / ".sstack.json").unlink()
        (self.root / "outside").symlink_to(self.root.parent)
        with self.assertRaises(ValueError):
            self.save(scope="outside/project")


if __name__ == "__main__":
    unittest.main()
