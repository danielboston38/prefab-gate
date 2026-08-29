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
        m = build_manifest(self.board, "10.0.5", Verdict(), [], self.tmp.name,
                           strict=False, out_dir="fab")
        self.assertEqual(m["board"]["sha256"], sha256(self.board))
        self.assertEqual(m["kicad_cli_version"], "10.0.5")

    def test_manifest_records_every_cosmetic_finding_it_let_past(self):
        waved = Finding(kind="violation", type="silk_overlap", description="Silk",
                        severity="warning", items=(), blocking=False, reason="warning")
        m = build_manifest(self.board, "10.0.5", Verdict(cosmetic=[waved]), [],
                           self.tmp.name, strict=False, out_dir="fab")
        self.assertEqual(len(m["verdict"]["cosmetic"]), 1)
        self.assertEqual(m["verdict"]["cosmetic"][0]["type"], "silk_overlap")

    def test_manifest_checksums_each_exported_file(self):
        m = build_manifest(self.board, "10.0.5", Verdict(), [self.board],
                           self.tmp.name, strict=False, out_dir="fab")
        self.assertEqual(m["files"][0]["sha256"], sha256(self.board))

    def test_manifest_records_file_paths_relative_to_package_root(self):
        gerber_dir = os.path.join(self.tmp.name, "gerbers")
        os.makedirs(gerber_dir)
        gerber = os.path.join(gerber_dir, "x.gbr")
        with open(gerber, "w") as fh:
            fh.write("x")
        m = build_manifest(self.board, "10.0.5", Verdict(), [gerber], self.tmp.name,
                           strict=False, out_dir="fab")
        self.assertEqual(m["files"][0]["name"], os.path.join("gerbers", "x.gbr"))

    def test_package_root_is_required_so_names_cannot_fall_back_to_basenames(self):
        """Two gerbers from different subdirectories would otherwise collide."""
        with self.assertRaises(TypeError):
            build_manifest(self.board, "10.0.5", Verdict(), [], strict=False,
                           out_dir="fab")

    def test_manifest_records_the_policy_the_run_used(self):
        """Two runs under different policies must not look identical later."""
        m = build_manifest(self.board, "10.0.5", Verdict(), [], self.tmp.name,
                           strict=True, out_dir="pcbway_production")
        self.assertIs(m["policy"]["strict"], True)
        self.assertEqual(m["policy"]["out_dir"], "pcbway_production")
