import copy
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from decomp_binary import Coff
from matched_source_manifest import extent, safe_path
from readability_scope import aggregate, digest, select_scope
from readability_review import DIMENSIONS


def entity(name="function", version="BW1W120", match="matched", variant="clear", **extra):
    return dict(identity=version + ":runblack:00800000", logical_id=name, version=version, match=match,
                reference_sha256="original", variant_sha256=variant, proof_sha256="all-relocations",
                ownership_complete=True, linked=False,
                ranges=[dict(path="src/mixed.cpp", start=1, end=3, role="definition", text="void f() {}")], **extra)


EXPECTED = dict(base="a" * 40, head="b" * 40, base_tree="c" * 40, head_tree="d" * 40)


def snapshot(entities, side):
    return dict(schema=1, verified=True, coverage_complete=True, revision=EXPECTED[side],
                tree=EXPECTED[side + "_tree"], entities=entities)


def scope(before, after):
    return select_scope(snapshot(before, "base"), snapshot(after, "head"), EXPECTED)


def review(item, value=20):
    span = item["ranges"][0]
    return dict(id=item["id"], variant_sha256=item["variant_sha256"],
                dimensions={name: value for name in DIMENSIONS}, rationale="Clear source with explicit intent",
                observations=[dict(path=span["path"], line=span["start"], severity="good", reason="Clear names")])


class ScopeTests(unittest.TestCase):
    def test_partial_tu_can_score_100_and_excluded_edits_do_not_change_input(self):
        old = entity(match="unmatched")
        first = scope([old], [entity()])
        unmatched = entity(name="excluded", match="unmatched", variant="unreadable")
        unmatched["identity"] += "1"
        second = scope([old], [entity(), unmatched])
        unmatched["variant_sha256"] = "even less readable"
        third = scope([old], [entity(), unmatched])
        self.assertEqual(first["eligible"], second["eligible"])
        self.assertEqual(second["eligible"], third["eligible"])
        result = aggregate(second, [review(second["eligible"][0])])
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["unmatched_excluded"], 1)

    def test_zero_eligible_is_na(self):
        result = aggregate(scope([], []), [])
        self.assertIsNone(result["score"])
        self.assertEqual(result["status"], "not_applicable")
        self.assertFalse(result["acceptance_ready"])

    def test_omission_is_pending_not_partial_number(self):
        selected = scope([], [entity()])
        result = aggregate(selected, [])
        self.assertIsNone(result["score"])
        self.assertEqual(result["reviewed"], 0)
        self.assertEqual(result["eligible"], 1)
        self.assertEqual(result["status"], "pending")

    def test_metadata_only_link_promotion_reviews_full_definition(self):
        old, new = entity(), entity()
        new["linked"] = True
        selected = scope([old], [new])
        self.assertEqual(len(selected["eligible"]), 1)
        self.assertEqual(selected["eligible"][0]["ranges"], new["ranges"])

    def test_existing_match_edit_is_reviewed(self):
        self.assertEqual(len(scope([entity(variant="before")], [entity()])["eligible"]), 1)
        self.assertEqual(len(scope([entity()], [entity()])["eligible"]), 0)

    def test_match_loss_blocks_acceptance_without_grading_unmatched_code(self):
        selected = scope([entity()], [entity(match="unmatched")])
        self.assertEqual(len(selected["regressions"]), 1)
        self.assertEqual(selected["eligible"], [])
        result = aggregate(selected, [])
        self.assertFalse(result["acceptance_ready"])
        self.assertIsNone(result["score"])

    def test_missing_prior_match_is_unknown(self):
        self.assertEqual(scope([entity()], [])["status"], "pending")

    def test_only_verified_version_qualifies(self):
        first = entity()
        second = entity(version="BW1W100", match="unmatched")
        selected = scope([], [first, second])
        self.assertEqual([v["version"] for v in selected["eligible"][0]["versions"]], ["BW1W120"])

    def test_identical_versions_vote_once_and_different_variants_vote_separately(self):
        first, second = entity(), entity(version="BW1W100")
        self.assertEqual(len(scope([], [first, second])["eligible"]), 1)
        second["variant_sha256"] = "different preprocessor variant"
        self.assertEqual(len(scope([], [first, second])["eligible"]), 2)

    def test_support_macros_fold_into_parent(self):
        item = entity()
        item["ranges"] += [dict(path="include/counts.h", start=1, end=245,
                                role="support", text="#define COUNT 12\n" * 245)]
        selected = scope([], [item])
        self.assertEqual(len(selected["eligible"]), 1)
        self.assertEqual(aggregate(selected, [review(selected["eligible"][0])])["score"], 100)

    def test_reference_change_is_not_progress(self):
        old, new = entity(), entity()
        new["reference_sha256"] = "redefined extent"
        self.assertEqual(scope([old], [new])["status"], "pending")

    def test_source_tree_revision_and_coverage_fail_closed(self):
        for key, value in (("verified", False), ("coverage_complete", False),
                           ("tree", "wrong"), ("revision", "wrong")):
            head = snapshot([entity()], "head")
            head[key] = value
            selected = select_scope(snapshot([], "base"), head, EXPECTED)
            self.assertEqual(selected["status"], "pending")
            self.assertEqual(selected["eligible"], [])

    def test_ambiguous_ownership_is_pending(self):
        item = entity()
        item["ownership_complete"] = False
        self.assertEqual(scope([], [item])["status"], "pending")

    def test_duplicate_original_identity_is_rejected(self):
        with self.assertRaises(ValueError):
            scope([], [entity(), entity()])

    def test_response_cannot_deduct_for_excluded_lines(self):
        selected = scope([], [entity()])
        response = review(selected["eligible"][0])
        response["observations"][0]["line"] = 4
        result = aggregate(selected, [response])
        self.assertIsNone(result["score"])
        self.assertTrue(result["errors"])

    def test_stale_duplicate_unknown_and_invalid_reviews_are_pending(self):
        selected = scope([], [entity()])
        good = review(selected["eligible"][0])
        for field, value in (("id", "unknown"), ("variant_sha256", "wrong"), ("dimensions", {})):
            bad = copy.deepcopy(good)
            bad[field] = value
            self.assertEqual(aggregate(selected, [bad])["status"], "pending")
        self.assertEqual(aggregate(selected, [good, good])["status"], "pending")

    def test_deterministic_mean_and_minimum(self):
        first, second = entity(), entity(name="other", variant="second")
        second["identity"] += "1"
        selected = scope([], [first, second])
        responses = [review(selected["eligible"][0]), review(selected["eligible"][1], 16)]
        result = aggregate(selected, responses)
        self.assertEqual(result["score"], 90)
        self.assertEqual(result["minimum"], 80)

    def test_missing_evidence_dryrun_is_pending(self):
        result = select_scope(None, None, EXPECTED)
        self.assertEqual(result["status"], "pending")
        self.assertEqual(len(result["unverified"]), 2)

    def test_malformed_model_types_fail_closed(self):
        selected = scope([], [entity()])
        for response in (None, {"id": []}):
            self.assertIsNone(aggregate(selected, [response])["score"])
        response = review(selected["eligible"][0])
        response["observations"][0]["path"] = []
        self.assertIsNone(aggregate(selected, [response])["score"])


def coff_with_relocations(two=True):
    # H136: C7 05 <destination> <pointer value>. Both operands relocate.
    code = bytes.fromhex("c7050000000000000000")
    relocations = [(2, 0, 6)] + ([(6, 1, 6)] if two else [])
    raw_offset = 60
    reloc_offset = raw_offset + len(code)
    symbol_offset = reloc_offset + 10 * len(relocations)
    header = struct.pack("<HHIIIHH", 0x14c, 1, 0, symbol_offset, 2, 0, 0)
    section = struct.pack("<8sIIIIIIHHI", b".text", 0, 0, len(code), raw_offset,
                          reloc_offset, 0, len(relocations), 0, 0x60000020)
    symbols = b"".join(struct.pack("<8sIhHBB", name, 0, 0, 0, 2, 0)
                       for name in (b"dest", b"pointer"))
    return Coff(header + section + code + b"".join(struct.pack("<IIH", *r) for r in relocations)
                + symbols + struct.pack("<I", 4))


class BinaryProofTests(unittest.TestCase):
    def test_secondary_relocation_cannot_disappear_behind_100_display(self):
        spec = dict(section=1, start=0, size=10)
        reference = extent(coff_with_relocations(), spec)
        missing_second = extent(coff_with_relocations(False), spec)
        self.assertEqual(len(reference["relocations"]), 2)
        self.assertNotEqual(reference, missing_second)

    def test_exact_operand_extent_preserved(self):
        spec = dict(section=1, start=0, size=10)
        self.assertEqual(extent(coff_with_relocations(), spec), extent(coff_with_relocations(), spec))
        self.assertNotEqual(digest(extent(coff_with_relocations(), spec)),
                            digest(extent(coff_with_relocations(False), spec)))

    def test_no_basename_or_traversal_path_guessing(self):
        self.assertNotEqual(safe_path("src/one/a.cpp"), safe_path("src/two/a.cpp"))
        for name in ("../a", "/a", "C:/a", "a/../b", "a\\b", "a//b"):
            with self.assertRaises(ValueError):
                safe_path(name)


if __name__ == "__main__":
    unittest.main()
