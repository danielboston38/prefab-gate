import os
import tempfile
import unittest
from gate.model import Finding, Parity, Verdict
from gate.manifest import (VerifiedArtifactChanged, build_manifest,
                          require_unchanged, sha256)


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
                           strict=False, out_dir="fab",
                           checked_board_sha256=sha256(self.board))
        self.assertEqual(m["board"]["sha256"], sha256(self.board))
        self.assertEqual(m["kicad_cli_version"], "10.0.5")

    def test_manifest_records_every_cosmetic_finding_it_let_past(self):
        waved = Finding(kind="violation", type="silk_overlap", description="Silk",
                        severity="warning", items=(), blocking=False, reason="warning")
        m = build_manifest(self.board, "10.0.5", Verdict(cosmetic=[waved]), [],
                           self.tmp.name, strict=False, out_dir="fab",
                           checked_board_sha256=sha256(self.board))
        self.assertEqual(len(m["verdict"]["cosmetic"]), 1)
        self.assertEqual(m["verdict"]["cosmetic"][0]["type"], "silk_overlap")

    def test_manifest_checksums_each_exported_file(self):
        m = build_manifest(self.board, "10.0.5", Verdict(), [self.board],
                           self.tmp.name, strict=False, out_dir="fab",
                           checked_board_sha256=sha256(self.board))
        self.assertEqual(m["files"][0]["sha256"], sha256(self.board))

    def test_manifest_records_file_paths_relative_to_package_root(self):
        gerber_dir = os.path.join(self.tmp.name, "gerbers")
        os.makedirs(gerber_dir)
        gerber = os.path.join(gerber_dir, "x.gbr")
        with open(gerber, "w") as fh:
            fh.write("x")
        m = build_manifest(self.board, "10.0.5", Verdict(), [gerber], self.tmp.name,
                           strict=False, out_dir="fab",
                           checked_board_sha256=sha256(self.board))
        self.assertEqual(m["files"][0]["name"], os.path.join("gerbers", "x.gbr"))

    def test_package_root_is_required_so_names_cannot_fall_back_to_basenames(self):
        """Two gerbers from different subdirectories would otherwise collide."""
        with self.assertRaises(TypeError):
            build_manifest(self.board, "10.0.5", Verdict(), [], strict=False,
                           out_dir="fab")

    def test_manifest_records_the_policy_the_run_used(self):
        """Two runs under different policies must not look identical later."""
        m = build_manifest(self.board, "10.0.5", Verdict(), [], self.tmp.name,
                           strict=True, out_dir="pcbway_production",
                           checked_board_sha256=sha256(self.board))
        self.assertIs(m["policy"]["strict"], True)
        self.assertEqual(m["policy"]["out_dir"], "pcbway_production")

    def test_manifest_records_what_the_gate_was_told_not_to_look_at(self):
        verdict = Verdict(excluded=2, ignored_checks=[
            {"key": "missing_courtyard", "description": "no courtyard"}])
        m = build_manifest(self.board, "10.0.5", verdict, [], self.tmp.name,
                           strict=False, out_dir="fab",
                           checked_board_sha256=sha256(self.board))
        self.assertEqual(m["verdict"]["excluded"], 2)
        self.assertEqual([c["key"] for c in m["verdict"]["ignored_checks"]],
                         ["missing_courtyard"])

    def test_manifest_records_whether_parity_ran(self):
        """A receipt that cannot tell "parity clean" from "parity never ran"
        is the exact hole this gate exists to close."""
        m = build_manifest(self.board, "10.0.5",
                           Verdict(parity=Parity(ran=False, reason="no schematic")),
                           [], self.tmp.name, strict=False, out_dir="fab",
                           checked_board_sha256=sha256(self.board))
        self.assertIs(m["verdict"]["parity"]["ran"], False)
        self.assertEqual(m["verdict"]["parity"]["reason"], "no schematic")


class TestRequireUnchanged(unittest.TestCase):
    """The gate's claim is that the artifacts verified are the artifacts sent.

    Hashing at verification time and again at packaging time only documents
    two states; it does not require them to be the same one. This is what
    turns the record into a requirement.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "b.kicad_pcb")
        with open(self.path, "w") as fh:
            fh.write("(kicad_pcb)")

    def test_an_unchanged_file_passes(self):
        require_unchanged(self.path, sha256(self.path), "the board")

    def test_a_changed_file_is_rejected(self):
        before = sha256(self.path)
        with open(self.path, "a") as fh:
            fh.write(" ")
        with self.assertRaises(VerifiedArtifactChanged):
            require_unchanged(self.path, before, "the board")

    def test_the_rejection_names_what_changed_and_where(self):
        before = sha256(self.path)
        with open(self.path, "a") as fh:
            fh.write(" ")
        with self.assertRaises(VerifiedArtifactChanged) as caught:
            require_unchanged(self.path, before, "the board")
        self.assertIn("the board", str(caught.exception))
        self.assertIn("b.kicad_pcb", str(caught.exception))

    def test_a_file_that_vanished_is_an_error_not_a_pass(self):
        before = sha256(self.path)
        os.remove(self.path)
        with self.assertRaises(OSError):
            require_unchanged(self.path, before, "the board")


class TestManifestRecordsWhatWasVerified(unittest.TestCase):
    """checked_sha256 and sha256 answer different questions.

    One says what the gate ran its checks against, the other says what went in
    the package. A receipt carrying only the second cannot show they were the
    same file.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.board = os.path.join(self.tmp.name, "b.kicad_pcb")
        with open(self.board, "w") as fh:
            fh.write("(kicad_pcb)")
        self.schematic = os.path.join(self.tmp.name, "b.kicad_sch")
        with open(self.schematic, "w") as fh:
            fh.write("(kicad_sch)")

    def test_the_board_carries_both_hashes(self):
        m = build_manifest(self.board, "10.0.5", Verdict(), [], self.tmp.name,
                           strict=False, out_dir="fab",
                           checked_board_sha256="deadbeef")
        self.assertEqual(m["board"]["checked_sha256"], "deadbeef")
        self.assertEqual(m["board"]["sha256"], sha256(self.board))

    def test_the_schematic_is_recorded_when_one_is_in_scope(self):
        m = build_manifest(self.board, "10.0.5", Verdict(), [], self.tmp.name,
                           strict=False, out_dir="fab",
                           checked_board_sha256="deadbeef",
                           schematic=self.schematic,
                           checked_schematic_sha256="cafe")
        self.assertEqual(m["schematic"]["path"], "b.kicad_sch")
        self.assertEqual(m["schematic"]["checked_sha256"], "cafe")
        self.assertEqual(m["schematic"]["sha256"], sha256(self.schematic))

    def test_a_pcb_only_package_records_no_schematic(self):
        m = build_manifest(self.board, "10.0.5", Verdict(), [], self.tmp.name,
                           strict=False, out_dir="fab",
                           checked_board_sha256="deadbeef")
        self.assertIsNone(m["schematic"])
