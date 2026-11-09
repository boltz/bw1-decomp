import copy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from matched_source_manifest import collect, sha256
from test_readability_scope import coff_with_relocations, extent_spec


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        for key, value in (("user.email", "test@example.invalid"), ("user.name", "Test")):
            subprocess.run(["git", "-C", str(self.repo), "config", key, value], check=True)
        (self.repo / "a.cpp").write_text("void clear() {}\nvoid unmatched() {}\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "fixture"], check=True)
        self.revision = subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip()
        self.tree = subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD^{tree}"], text=True).strip()
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        self.inputs = []
        for path, kind, data in (("original.o", "reference", coff_with_relocations().data),
                                  ("compiled.o", "object", coff_with_relocations().data),
                                  ("cl.exe", "compiler", b"original compiler fixture"),
                                  ("command.json", "profile", b"exact flags fixture"),
                                  ("symbols.txt", "metadata", b"original reference identity fixture")):
            (self.artifacts / path).write_bytes(data)
            self.inputs.append(dict(path=path, kind=kind, sha256=sha256(data)))
        self.inputs.append(dict(path="a.cpp", kind="source", sha256=sha256((self.repo / "a.cpp").read_bytes())))
        self.plan = dict(revision=self.revision, tree=self.tree, compiled_tree=self.tree, clean_build=True,
                         dependencies_complete=True, entities_complete=True, ownership_reviewed=True,
                         compiler_sha256=self.inputs[2]["sha256"], profile_sha256=self.inputs[3]["sha256"],
                         inputs=self.inputs, entities=[dict(identity="BW1W120:runblack:00800000", version="BW1W120",
                             module="runblack", address=0x800000, logical_id="clear()", context_sha256="support context",
                             ownership_complete=True, ranges=[dict(path="a.cpp", start=1, end=1, role="definition")],
                             parts=[dict(reference=dict(path="original.o", **extent_spec()),
                                         candidate=dict(path="compiled.o", **extent_spec()))])])

    def collect(self):
        return collect(self.plan, self.repo, self.artifacts, self.revision, self.tree)

    def test_complete_trusted_bundle_proves_exact_entity(self):
        result = self.collect()
        self.assertTrue(result["verified"])
        self.assertEqual(result["entities"][0]["match"], "matched")
        self.assertEqual(result["entities"][0]["ranges"][0]["text"], "void clear() {}\n")

    def test_stale_object_hash_never_proves_match(self):
        (self.artifacts / "compiled.o").write_bytes(b"stale")
        self.assertFalse(self.collect()["verified"])

    def test_wrong_compiled_tree_or_missing_dependencies_is_unverified(self):
        for key, value in (("compiled_tree", "wrong"), ("dependencies_complete", False),
                           ("ownership_reviewed", False), ("entities_complete", False)):
            original = self.plan[key]
            self.plan[key] = value
            self.assertFalse(self.collect()["verified"])
            self.plan[key] = original

    def test_second_relocation_loss_is_unmatched_even_with_fresh_hashes(self):
        data = coff_with_relocations(False).data
        (self.artifacts / "compiled.o").write_bytes(data)
        self.plan["inputs"][1]["sha256"] = sha256(data)
        self.assertEqual(self.collect()["entities"][0]["match"], "unmatched")

    def test_extent_outside_object_or_source_is_unverified(self):
        self.plan["entities"][0]["ranges"][0]["end"] = 500
        self.assertEqual(self.collect()["entities"][0]["match"], "unverified")

    def test_compiler_fingerprint_requires_actual_input(self):
        self.plan["compiler_sha256"] = "invented profile"
        self.assertFalse(self.collect()["verified"])

    def test_cli_rejects_unpinned_pr_bundle(self):
        import json
        bundle = self.root / "candidate.json"
        bundle.write_text(json.dumps(dict(base=self.plan, head=self.plan)))
        result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "matched_source_manifest.py"),
            "--repo", str(self.repo), "--base", self.revision, "--head", self.revision,
            "--bundle", str(bundle), "--artifact-root", str(self.artifacts), "--output", str(self.root / "result.json")],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("independently trusted", result.stderr)


if __name__ == "__main__":
    unittest.main()
