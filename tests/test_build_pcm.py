"""The archive must match KiCad's PCM layout exactly."""
import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "kicad"))

import build_pcm  # noqa: E402

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     ".."))


class BuildTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.TemporaryDirectory()
        cls.archive, cls.submission = build_pcm.build(REPO, cls.out.name)
        with zipfile.ZipFile(cls.archive) as zf:
            cls.names = set(zf.namelist())
            cls.packed = json.loads(zf.read("metadata.json"))

    @classmethod
    def tearDownClass(cls):
        cls.out.cleanup()

    def test_metadata_sits_at_the_archive_root(self):
        self.assertIn("metadata.json", self.names)

    def test_plugin_code_is_under_plugins(self):
        for expected in ("plugins/__init__.py", "plugins/action.py",
                         "plugins/staging.py", "plugins/runner.py",
                         "plugins/summary.py"):
            self.assertIn(expected, self.names)

    def test_the_gate_package_travels_with_the_plugin(self):
        """The plugin imports gate/ — shipping without it installs a plugin
        that cannot run."""
        self.assertTrue(any(n.startswith("plugins/gate/") for n in self.names))
        self.assertIn("plugins/prefab_gate.py", self.names)

    def test_both_icons_are_present(self):
        self.assertIn("resources/icon.png", self.names)
        self.assertIn("plugins/icon24.png", self.names)

    def test_archive_metadata_omits_download_fields(self):
        """The spec forbids them inside the package."""
        for banned in ("download_sha256", "download_url", "download_size",
                       "install_size"):
            self.assertNotIn(banned, self.packed["versions"][0])

    def test_submission_metadata_carries_the_download_fields(self):
        version = self.submission["versions"][0]
        self.assertEqual(64, len(version["download_sha256"]))
        self.assertGreater(version["download_size"], 0)
        self.assertGreater(version["install_size"], 0)

    def test_the_sha256_actually_describes_the_archive(self):
        """A hash maintained beside the artifact rather than from it is the
        thing that drifts."""
        import hashlib
        with open(self.archive, "rb") as handle:
            actual = hashlib.sha256(handle.read()).hexdigest()
        self.assertEqual(actual,
                         self.submission["versions"][0]["download_sha256"])

    def test_version_has_no_prerelease_suffix(self):
        """The v2 schema rejects them; intent belongs in status."""
        self.assertRegex(self.submission["versions"][0]["version"],
                         r"^\d{1,4}(\.\d{1,4}(\.\d{1,6})?)?$")

    def test_identifier_matches_the_schema(self):
        self.assertRegex(self.submission["identifier"],
                         r"^[a-zA-Z][-a-zA-Z0-9.]{0,98}[a-zA-Z0-9]$")

    def test_required_top_level_fields_are_present(self):
        """resources is required by the v2 schema, though the prose docs read
        as though it were optional."""
        for field in ("name", "description", "description_full", "identifier",
                      "type", "author", "license", "resources", "versions"):
            self.assertIn(field, self.packed)

    def test_schema_bounded_fields_are_within_limits(self):
        self.assertLessEqual(len(self.packed["name"]), 200)
        self.assertLessEqual(len(self.packed["description"]), 500)
        self.assertLessEqual(len(self.packed["description_full"]), 5000)

    def test_tags_match_the_schema_pattern(self):
        for tag in self.packed.get("tags", []):
            self.assertRegex(tag, r"^[a-z][-a-z0-9]{0,48}[a-z0-9]$")

    def test_no_pycache_is_shipped(self):
        self.assertFalse([n for n in self.names if "__pycache__" in n])
        self.assertFalse([n for n in self.names if n.endswith(".pyc")])


if __name__ == "__main__":
    unittest.main()
