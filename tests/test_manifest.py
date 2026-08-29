import os
import tempfile
import unittest
from gate.model import Finding, Verdict
from gate.manifest import sha256, build_manifest


class TestManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.board = os.path.join(self.tmp.name, "b.kicad_pcb")
        with open(self.board, "w") as fh:
            fh.write("(kicad_pcb)")
        self.addCleanup(self.tmp.cleanup)

    def test_sha256_is_stable_and_content_dependent(self):
        first = sha256(self.board)
        self.assertEqual(first, sha256(self.board))
        with open(self.board, "a") as fh:
            fh.write(" ")
        self.assertNotEqual(first, sha256(self.board))

    def test_manifest_records_board_hash_and_cli_version(self):
        m = build_manifest(self.board, "10.0.5", Verdict(), [])
        self.assertEqual(m["board"]["sha256"], sha256(self.board))
        self.assertEqual(m["kicad_cli_version"], "10.0.5")

    def test_manifest_records_every_cosmetic_finding_it_let_past(self):
        waved = Finding(kind="violation", type="silk_overlap", description="Silk",
                        severity="warning", items=(), blocking=False, reason="warning")
        m = build_manifest(self.board, "10.0.5", Verdict(cosmetic=[waved]), [])
        self.assertEqual(len(m["verdict"]["cosmetic"]), 1)
        self.assertEqual(m["verdict"]["cosmetic"][0]["type"], "silk_overlap")

    def test_manifest_checksums_each_exported_file(self):
        m = build_manifest(self.board, "10.0.5", Verdict(), [self.board])
        self.assertEqual(m["files"][0]["sha256"], sha256(self.board))
