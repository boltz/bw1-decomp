"""Token inventories and scorecard validation use synthetic changes, not a model API."""

import unittest

from tools import review_quality as audit
from tools import readability_review as scorecard
from tools.automatic_pr_review import make_review_body, safe_markdown, choose_review_event


def inventory(text, path="src/example.cpp", added=None):
    added = set(range(1, len(text.splitlines()) + 1)) if added is None else set(added)
    patch = "@@ -0,0 +1,{} @@\n".format(len(text.splitlines()))
    patch += "\n".join(("+" if line in added else " ") + value for line, value in enumerate(text.splitlines(), 1))
    return audit.inventory(
        [{"filename": path, "patch": patch, "additions": len(added)}],
        [{"path": path, "text": text, "status": "complete"}],
    )


def quality():
    return {
        "dimensions": dict.fromkeys(scorecard.DIMENSIONS, 16),
        "rationale": "The helper is easy to follow, but the limit needs a clear name.",
        "lionhead_context": "Using min fits this project's older C++ tools. That does not prove Lionhead wrote it this way.",
        "precedent_summary": "The supplied reviews did not show a clear decision on similar code.",
        "good": [
            {
                "path": "src/example.cpp",
                "line": 4,
                "reason": "Using min makes it easy to see where the value is capped.",
                "suggestion": "",
            }
        ],
        "bad": [],
        "precedents": [],
        "numbers_reviewed": True,
        "numeric_decisions": [
            {
                "ids": ["N1"],
                "classification": "magic",
                "reason": "The number does not tell the reader what the limit means.",
                "suggestion": "Use the existing named capacity if one is defined.",
            }
        ],
    }


EXAMPLE = "int LimitItems(int count)\n{\n    // Cap the items.\n    return min(count, 37);\n}\n"


class TokenInventoryTests(unittest.TestCase):
    def test_cpp_strings_chars_comments_and_identifiers_are_not_numeric_literals(self):
        text = "const char* s = \"123 // not a comment\";\nint field_0x80 = 37; // 999\nchar c = '3';\n"
        result = inventory(text)
        self.assertEqual([n["literal"] for n in result["numbers"]], ["37"])
        self.assertEqual(result["comment_count"], 1)
        self.assertEqual(result["remove_comment_count"], 1)

    def test_only_added_lines_count(self):
        result = inventory("// Existing comment\nint old = 9;\nint added = 5;\n", added={3})
        self.assertEqual(result["comment_count"], 0)
        self.assertEqual([n["literal"] for n in result["numbers"]], ["5"])

    def test_block_comment_with_added_continuation_is_counted_once(self):
        result = inventory("/* Existing first line\n added explanation 123\n*/\n", added={2})
        self.assertEqual(result["comment_count"], 1)
        self.assertEqual(result["comments"][0]["line"], 2)
        self.assertEqual(result["number_count"], 0)

    def test_continued_cpp_line_comment_hides_following_literal(self):
        result = inventory("// continued \\\ncomment 99\nint x = 7;\n")
        self.assertEqual([n["literal"] for n in result["numbers"]], ["7"])
        self.assertEqual(result["comment_count"], 1)

    def test_allowed_annotations_are_counted_separately(self):
        text = (
            "// Inliner IL size: 12\n// BW1W120 00401000 BW1M119 null\nvoid F();\n"
            "// clang-format off\nint a[] = {\n  7, //\n};\n// clang-format on\n"
        )
        result = inventory(text, "src/example.h")
        self.assertEqual(result["comment_count"], 5)
        self.assertEqual(result["remove_comment_count"], 0)
        self.assertEqual(result["allowed_comment_count"], 5)

    def test_cpp_definition_address_comment_is_not_a_required_exception(self):
        text = "// BW1W120 00401000\nvoid F()\n{\n}\n"
        self.assertEqual(inventory(text)["remove_comment_count"], 1)
        self.assertEqual(inventory("// BW1W120 00401000\nstatic void F();\n")["remove_comment_count"], 0)

    def test_python_docstrings_strings_and_directives(self):
        text = '#!/usr/bin/env python3\n"""Documentation 55 # string"""\nx = "# 66"\ny = 37 # explanation\n'
        result = inventory(text, "tools/example.py")
        self.assertEqual([n["literal"] for n in result["numbers"]], ["37"])
        self.assertEqual(result["comment_count"], 2)
        self.assertEqual(result["allowed_comment_count"], 1)
        self.assertEqual(result["remove_comment_count"], 1)

    def test_yaml_strings_and_embedded_scripts_are_excluded(self):
        text = 'timeout-minutes: 45 # explanation\nname: "# 66"\nrun: |\n  echo 77 # script data\n# outside\n'
        result = inventory(text, ".github/workflows/example.yml")
        self.assertEqual([n["literal"] for n in result["numbers"]], ["45"])
        self.assertEqual(result["comment_count"], 2)

    def test_vendored_code_and_documentation_are_excluded(self):
        for path in ("src/zlib/test.c", "src/GameSpy/test.cpp", "README.md"):
            result = inventory("// comment\nint x = 37;\n", path)
            self.assertEqual(result["eligible_files"], 0)
            self.assertEqual(result["number_count"], 0)

    def test_sky_sized_number_inventory_is_not_truncated(self):
        text = "\n".join("int value{} = {};".format(i, i) for i in range(349))
        result = inventory(text)
        self.assertEqual(result["number_count"], 349)
        self.assertEqual(len(result["numbers"]), 349)
        self.assertEqual(result["limitations"], [])

    def test_number_cap_does_not_make_complete_comment_audit_incomplete(self):
        result = inventory("\n".join("int v{} = {};".format(i, i) for i in range(audit.MAX_NUMBERS + 1)))
        self.assertEqual(result["number_count"], audit.MAX_NUMBERS + 1)
        self.assertEqual(len(result["numbers"]), audit.MAX_NUMBERS)
        self.assertTrue(result["limitations"])
        self.assertTrue(result["comments_complete"])

    def test_missing_and_truncated_context_never_claim_complete_counts(self):
        result = audit.inventory([{"filename": "src/missing.cpp", "patch": None}], [])
        self.assertFalse(result["comments_complete"])
        self.assertTrue(result["limitations"])
        result = audit.inventory(
            [{"filename": "src/file.cpp", "patch": "@@ -0,0 +1 @@\n+int x = 3;", "additions": 2}],
            [{"path": "src/file.cpp", "text": "int x = 3;", "status": "truncated"}],
        )
        self.assertFalse(result["comments_complete"])


class QualityScorecardTests(unittest.TestCase):
    def validate(self, model=None, source=None, citations=None):
        return scorecard.validate_quality(
            model if model is not None else quality(),
            source if source is not None else inventory(EXAMPLE),
            {"src/example.cpp": {1, 2, 3, 4, 5}},
            citations or {},
        )

    def test_score_counts_locations_and_formatting_are_visible(self):
        result = self.validate()
        self.assertEqual(result["score"], 80)
        self.assertEqual(len(result["magic"]), 1)
        self.assertTrue(result["blocking"])
        body = make_review_body([], "abcdef", "REQUEST_CHANGES", 0, 0, quality=result)
        self.assertIn("| Human readability | 80 / 100 |", body)
        self.assertIn("1 found; 0 still unclear", body)
        self.assertIn("1 total; 1 to remove; 0 required comments kept", body)
        self.assertIn("## Human readability", body)
        self.assertIn("## Past reviews from RepoScout", body)
        self.assertIn("src/example.cpp:4", body)
        self.assertIn("Remove 1 added or edited comment.", body)
        self.assertNotIn("No actionable findings", body)

    def test_clean_numeric_audit_explicitly_praises_no_magic_numbers(self):
        raw = quality()
        raw["numeric_decisions"][0].update(
            classification="justified", reason="This test input has an explicit expected meaning.", suggestion=""
        )
        result = self.validate(raw, inventory("int LimitItems(int count)\n{\n\n    return min(count, 37);\n}\n"))
        self.assertFalse(result["blocking"])
        self.assertIn("Good: no magic numbers found", "\n".join(scorecard.render_quality(result, safe_markdown)))

    def test_unclassified_numeric_uses_prevent_clean_result(self):
        raw = quality()
        raw["numeric_decisions"] = []
        result = self.validate(raw)
        self.assertFalse(result["numbers_complete"])
        self.assertEqual(result["unresolved_numbers"], 1)
        text = "\n".join(scorecard.render_quality(result, safe_markdown))
        self.assertNotIn("Good: no magic numbers", text)

    def test_duplicate_and_fabricated_numeric_ids_are_invalid(self):
        raw = quality()
        raw["numeric_decisions"][0]["ids"] = ["N1", "N1", "invented"]
        result = self.validate(raw)
        self.assertEqual(result["invalid"], 2)
        self.assertFalse(result["numbers_complete"])

    def test_uncertain_numbers_remain_unresolved(self):
        raw = quality()
        raw["numeric_decisions"][0]["classification"] = "uncertain"
        result = self.validate(raw)
        self.assertEqual(len(result["magic"]), 0)
        self.assertEqual(result["unresolved_numbers"], 1)
        self.assertFalse(result["numbers_complete"])

    def test_dimension_range_boolean_and_unsupported_locations_are_rejected(self):
        for value in (True, -1, 21):
            raw = quality()
            raw["dimensions"]["naming"] = value
            self.assertIsNone(self.validate(raw)["score"])
        raw = quality()
        raw["good"][0]["line"] = 99
        self.assertTrue(self.validate(raw)["invalid"])

    def test_missing_quality_still_renders_every_metric_as_unavailable(self):
        result = self.validate({})
        text = "\n".join(scorecard.render_quality(result, safe_markdown))
        self.assertIn("Human readability", text)
        self.assertIn("Magic numbers", text)
        self.assertIn("Added/edited comments", text)
        self.assertIsNone(result["score"])
        self.assertTrue(result["invalid"])

    def test_citations_must_come_from_supplied_discussion_evidence(self):
        raw = quality()
        raw["precedents"] = [
            {
                "url": "https://github.com/openblack/bw1-decomp/pull/9#review",
                "comparison": "The reviewer preferred the existing helper.",
                "position": "rejected",
                "quote": "Use the existing helper.",
            }
        ]
        self.assertTrue(self.validate(raw)["invalid"])
        row = {
            "url": raw["precedents"][0]["url"],
            "pr_number": 9,
            "author": "reviewer",
            "author_association": "CONTRIBUTOR",
            "review_state": "CHANGES_REQUESTED",
            "excerpt": "Use the existing helper.",
        }
        result = self.validate(raw, citations={row["url"]: row})
        self.assertEqual(len(result["precedents"]), 1)
        text = "\n".join(scorecard.render_quality(result, safe_markdown))
        self.assertIn("CONTRIBUTOR", text)
        self.assertIn("CHANGES_REQUESTED", text)
        self.assertNotIn("maintainer approved", text)

    def test_pr_metadata_is_not_a_maintainer_decision(self):
        evidence = {
            "queries": [
                {"results": [{"url": "https://github.com/openblack/bw1-decomp/pull/1", "kind": "pull_request"}]}
            ]
        }
        self.assertEqual(scorecard.precedent_sources(evidence), {})

    def test_medium_readability_findings_request_changes(self):
        finding = {"classification": "maintainability/readability issue", "severity": "medium"}
        self.assertEqual(choose_review_event([finding], 0, 0), "REQUEST_CHANGES")
        self.assertEqual(choose_review_event([finding], 1, 0), "COMMENT")

    def test_comment_text_cannot_inject_mentions_or_html(self):
        result = self.validate(source=inventory("int F()\n{\n// @everyone <script>\nreturn 37;\n}\n"))
        body = "\n".join(scorecard.render_quality(result, safe_markdown))
        self.assertNotIn("@everyone", body)
        self.assertNotIn("<script>", body)


class AdditionalQualityPolicyTests(unittest.TestCase):
    def test_known_quality_changes_request_changes_even_when_binary_context_is_limited(self):
        result = scorecard.validate_quality(quality(), inventory(EXAMPLE), {"src/example.cpp": {1, 2, 3, 4, 5}}, {})
        self.assertEqual(scorecard.apply_quality_event("COMMENT", result), "REQUEST_CHANGES")

    def test_unknown_score_and_numbers_never_approve_in_main_decision(self):
        result = scorecard.validate_quality({}, inventory("int x = 37;"), {"src/example.cpp": {1}}, {})
        self.assertTrue(result["invalid"])
        self.assertFalse(result["numbers_complete"])
        base = choose_review_event([], 0, 0, limited_context_files=int(result["invalid"] > 0))
        self.assertEqual(scorecard.apply_quality_event(base, result), "COMMENT")

    def test_no_source_score_is_not_invented_for_documentation(self):
        raw = quality()
        raw.update(good=[], bad=[], numeric_decisions=[])
        result = scorecard.validate_quality(raw, inventory("# Notes", "README.md"), {"README.md": {1}}, {})
        self.assertIsNone(result["score"])
        self.assertIn("N/A / 100", "\n".join(scorecard.render_quality(result, safe_markdown)))

    def test_malformed_example_path_does_not_crash_validation(self):
        raw = quality()
        raw["good"][0]["path"] = []
        result = scorecard.validate_quality(raw, inventory(EXAMPLE), {"src/example.cpp": {1, 2, 3, 4, 5}}, {})
        self.assertTrue(result["invalid"])

    def test_invented_quote_cannot_be_used_as_acceptance_evidence(self):
        raw = quality()
        url = "https://github.com/openblack/bw1-decomp/pull/9#review"
        raw["precedents"] = [
            {"url": url, "position": "accepted", "quote": "This is excellent.", "comparison": "Same helper."}
        ]
        supplied = {url: {"url": url, "excerpt": "Please change this.", "author_association": "MEMBER"}}
        result = scorecard.validate_quality(raw, inventory(EXAMPLE), {"src/example.cpp": {1, 2, 3, 4, 5}}, supplied)
        self.assertTrue(result["invalid"])
        self.assertEqual(result["precedents"], [])

    def test_added_comment_block_records_which_lines_are_ours(self):
        result = inventory("/* Existing\nnew prose\n*/\n", added={2})
        self.assertFalse(result["comments"][0]["started_in_added_line"])
        self.assertEqual(result["comments"][0]["added_lines"], [2])

    def test_missing_patch_with_zero_additions_has_no_new_comments(self):
        result = audit.inventory([{"filename": "src/file.cpp", "patch": None, "additions": 0}], [])
        self.assertTrue(result["comments_complete"])
        self.assertEqual(result["comment_count"], 0)


class PlainReviewWritingTests(unittest.TestCase):
    def test_visible_report_uses_plain_text_and_keeps_counts(self):
        import re

        result = scorecard.validate_quality(quality(), inventory(EXAMPLE), {"src/example.cpp": set(range(1, 6))}, {})
        result["inventory"]["limitations"] = ["src/example.cpp: source context is incomplete"]
        result["inventory"]["comments_complete"] = False
        body = make_review_body([], "abcdef", "REQUEST_CHANGES", 1, 0, quality=result)
        visible = re.sub(r"<details>.*?</details>", "", body, flags=re.S)
        self.assertTrue(body.startswith("<!-- bw1-automatic-review -->\nFix the issues below before merging."))
        self.assertIn("| Human readability | 80 / 100 (partial review) |", visible)
        self.assertIn("1 found; 0 still unclear; checked: 1", visible)
        self.assertIn("1 to remove", visible)
        self.assertIn("Lionhead C++ style", visible)
        self.assertIn("Some files or results were missing", visible)
        self.assertNotIn("source context is incomplete", visible)
        self.assertNotIn("naming 16/20", visible)
        self.assertIn("source context is incomplete", body)
        for phrase in (
            "**",
            "\u2014",
            "\u2013",
            "provisional",
            "inspected literals",
            "source fidelity",
            "plausibility",
        ):
            self.assertNotIn(phrase, body)
        self.assertEqual(body.count("<details>"), body.count("</details>"))

    def test_required_comment_locations_are_collapsed_not_dropped(self):
        import re

        source = "// BW1W120 00401000\nstatic void F();\n"
        inv = inventory(source)
        raw = quality()
        raw["numeric_decisions"] = []
        raw["good"][0]["line"] = 2
        result = scorecard.validate_quality(raw, inv, {"src/example.cpp": {1, 2}}, {})
        body = "\n".join(scorecard.render_quality(result, safe_markdown))
        visible = re.sub(r"<details>.*?</details>", "", body, flags=re.S)
        self.assertIn("1 required comments kept", visible)
        self.assertIn("Required comments kept (1)", body)
        self.assertIn("src/example.cpp:1", body)
        self.assertNotIn("src/example.cpp:1", visible)

    def test_fix_comes_before_reason_and_build_evidence_is_collapsed(self):
        import re

        finding = dict(
            path="src/example.cpp",
            line=1,
            function="",
            severity="medium",
            classification="maintainability/readability issue",
            title="Remove the include comments",
            suggestion="Remove the comments beside the includes.",
            why_it_matters="The header names already explain them.",
            evidence="Exact compiler evidence.",
            assumptions="",
            matching_effect="",
            source_linking="",
            checks="",
            unresolved_decision="",
        )
        body = make_review_body([finding], "abcdef", "REQUEST_CHANGES", 0, 0)
        visible = re.sub(r"<details>.*?</details>", "", body, flags=re.S)
        self.assertLess(visible.index(finding["suggestion"]), visible.index(finding["why_it_matters"]))
        self.assertNotIn(finding["evidence"], visible)
        self.assertIn(finding["evidence"], body)


class OwnerReviewScopeTests(unittest.TestCase):
    def test_scope_is_specific_to_owner_exclusions(self):
        for path in (
            "configure.py",
            "tools/thing.py",
            "tools/tests/test_thing.py",
            ".claude/skills/task/run.py",
            "tools/types.pyi",
        ):
            self.assertFalse(audit.reviewable_path(path), path)
        for path in (
            "src/example.cpp",
            "src/example.h",
            "config/BW1W120/symbols.txt",
            "tools/README.md",
            "scripts/other.py",
        ):
            self.assertTrue(audit.reviewable_path(path), path)

    def test_git_comment_lint_skips_excluded_python(self):
        from unittest import mock

        fake_paths = b"configure.py\0tools/helper.py\0.claude/skills/task/run.py\0"
        with (
            mock.patch.object(audit.subprocess, "check_output", side_effect=["base", "head", fake_paths, fake_paths]),
            mock.patch.object(audit.subprocess, "run") as show,
        ):
            result = audit.git_inventory("base", "head")
        self.assertEqual(result["eligible_files"], 0)
        self.assertEqual(result["comment_count"], 0)
        show.assert_not_called()


class BaseCommentTests(unittest.TestCase):
    def audit_change(self, before, after):
        path = "src/example.cpp"
        signatures, complete = audit.comment_signatures(path, before)
        patch = "@@ -0,0 +1,{} @@\n".format(len(after.splitlines())) + "\n".join(
            "+" + line for line in after.splitlines()
        )
        return audit.inventory(
            [{"filename": path, "patch": patch}],
            [
                {
                    "path": path,
                    "text": after,
                    "status": "complete",
                    "base_comment_signatures": signatures,
                    "base_comments_complete": complete,
                }
            ],
            base_context_required=True,
        )

    def test_unchanged_trailing_comment_is_not_added(self):
        result = self.audit_change("int limit = 3; // existing\n", "int limit = 4; // existing\n")
        self.assertEqual(result["comment_count"], 0)
        self.assertEqual(result["number_count"], 1)

    def test_moved_comments_are_not_added(self):
        result = self.audit_change("// existing\nint value;\n", "int value;\n// existing\n")
        self.assertEqual(result["comment_count"], 0)

    def test_duplicate_comment_is_counted_once(self):
        result = self.audit_change("// existing\n", "// existing\n// existing\n")
        self.assertEqual(result["remove_comment_count"], 1)

    def test_edit_beyond_display_limit_is_detected(self):
        prefix = "/* " + "old " * 100
        result = self.audit_change(prefix + "before */", prefix + "after */")
        self.assertEqual(result["remove_comment_count"], 1)

    def test_missing_base_is_incomplete_without_false_removal(self):
        result = audit.inventory(
            [{"filename": "src/a.cpp", "patch": "@@ -1 +1 @@\n+int x; // old"}],
            [{"path": "src/a.cpp", "text": "int x; // old", "status": "complete"}],
            base_context_required=True,
        )
        self.assertFalse(result["comments_complete"])
        self.assertEqual(result["comment_count"], 0)

    def test_raw_strings_do_not_contribute_comments_or_numbers(self):
        numbers, comments, complete = audit.scan_file("src/a.cpp", 'const char* s = R"tag(// 123)tag";', {1})
        self.assertTrue(complete)
        self.assertEqual((numbers, comments), ([], []))

    def test_unterminated_comment_is_incomplete(self):
        _, _, complete = audit.scan_file("src/a.cpp", "/* incomplete", {1})
        self.assertFalse(complete)


class ReviewIntegrationTests(unittest.TestCase):
    def test_posted_review_has_metrics_and_comment_request_despite_missing_binary_evidence(self):
        import json
        import os
        from pathlib import Path
        import tempfile
        from unittest import mock
        import tools.automatic_pr_review as reviewer

        patch = "@@ -0,0 +1,5 @@\n" + "\n".join("+" + line for line in EXAMPLE.splitlines())
        files = [{"filename": "src/example.cpp", "patch": patch, "additions": 5, "deletions": 0}]
        pr = {
            "state": "open",
            "draft": False,
            "head": {"sha": "head"},
            "base": {"sha": "base"},
            "title": "Example",
            "body": "",
        }
        github = mock.MagicMock()
        github.request.return_value = pr
        github.list_changed_files.return_value = files, False
        github.list_check_runs.return_value = [], False
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, text in [("guide.md", "Guide"), ("instructions.md", "Instructions"), ("event.json", "{}")]:
                (root / name).write_text(text)
            environment = {
                "GITHUB_REPOSITORY": "boltz/bw1-decomp",
                "GITHUB_TOKEN": "test-token",
                "PR_NUMBER": "1",
                "PR_REVIEW_API_KEY": "test-key",
                "PR_REVIEW_MODEL": "test-model",
                "PR_REVIEW_GUIDE": str(root / "guide.md"),
                "PR_REVIEW_INSTRUCTIONS": str(root / "instructions.md"),
                "GITHUB_EVENT_PATH": str(root / "event.json"),
                "PR_REVIEW_QUALITY_REPORT": str(root / "quality.json"),
            }
            with (
                mock.patch.dict(os.environ, environment),
                mock.patch.object(reviewer, "GitHub", return_value=github),
                mock.patch.object(
                    reviewer,
                    "collect_source_context",
                    return_value=(
                        [
                            {
                                "path": "src/example.cpp",
                                "text": EXAMPLE,
                                "status": "complete",
                                "base_comment_signatures": [],
                                "base_comments_complete": True,
                            }
                        ],
                        0,
                    ),
                ),
                mock.patch.object(reviewer, "collect_configure_status", return_value=[]),
                mock.patch.object(reviewer, "collect_caller_context", return_value=[]),
                mock.patch.object(
                    reviewer, "collect_reposcout_evidence", return_value={"status": "unavailable", "queries": []}
                ),
                mock.patch.object(reviewer, "load_binary_evidence", return_value=([], True)),
                mock.patch.object(reviewer, "call_model", return_value={"findings": [], "quality": quality()}),
            ):
                reviewer.main()
            submitted = github.submit_review.call_args.args
            self.assertEqual(submitted[2], "REQUEST_CHANGES")
            self.assertIn("| Human readability | 80 / 100 |", submitted[3])
            self.assertIn("1 found; 0 still unclear", submitted[3])
            self.assertIn("Remove 1 added or edited comment.", submitted[3])
            self.assertIn("Binary comparison evidence was unavailable", submitted[3])
            artifact = json.loads((root / "quality.json").read_text())
            self.assertEqual(artifact["inventory"]["comment_count"], 1)
            self.assertEqual(artifact["score"], 80)
            self.assertEqual(len(artifact["magic"]), 1)


if __name__ == "__main__":
    unittest.main()
