import json
import unittest
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import tools.automatic_pr_review as automatic_pr_review
from tools.automatic_pr_review import (
    GitHub,
    added_line_numbers,
    build_diff_context,
    choose_review_event,
    collect_configure_status,
    collect_source_context,
    call_model,
    make_review_body,
    render_requested_changes,
    make_prompt,
    response_output_text,
    safe_markdown,
    valid_findings,
)


class AutomaticReviewTests(unittest.TestCase):
    def test_reposcout_reports_missing_index_without_claiming_search(self):
        with mock.patch.dict("os.environ", {"PR_REVIEW_REPOSCOUT_DB": "/nonexistent/reposcout.sqlite3"}):
            evidence = automatic_pr_review.collect_reposcout_evidence([])
        self.assertIn("unavailable", evidence["status"])
        self.assertNotIn("queried", automatic_pr_review.reposcout_review_status(evidence))

    def test_reposcout_queries_existing_index_read_only_and_keeps_citations(self):
        from tools import reposcout

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.sqlite3"
            db = reposcout.connect(path)
            pull = {
                "number": 12,
                "title": "LH3DSky review",
                "body": "Preserve original behavior",
                "merged_at": "2026-01-02T00:00:00Z",
                "user": {},
                "html_url": "https://github.com/openblack/bw1-decomp/pull/12",
            }
            reposcout.replace_repository_data(
                db,
                reposcout.REPOSITORY,
                [pull],
                [
                    reposcout._pull_doc(reposcout.REPOSITORY, pull),
                    reposcout._document(
                        reposcout.REPOSITORY,
                        12,
                        "review",
                        {
                            "id": 1,
                            "body": "Use LH3DSky.",
                            "state": "APPROVED",
                            "user": {"login": "maintainer"},
                            "author_association": "MEMBER",
                            "html_url": pull["html_url"] + "#pullrequestreview-1",
                        },
                    ),
                ],
                [],
            )
            db.close()
            before = path.read_bytes()
            with mock.patch.dict("os.environ", {"PR_REVIEW_REPOSCOUT_DB": str(path)}):
                evidence = automatic_pr_review.collect_reposcout_evidence(
                    [{"filename": "src/Lionhead/LH3DSky.cpp"}, {"filename": "src/Lionhead/LH3DSky.h"}]
                )
            self.assertEqual(evidence["status"], "queried index")
            self.assertEqual(len(evidence["queries"]), 7)
            self.assertEqual(evidence["queries"][0]["results"][0]["pr_url"], pull["html_url"])
            self.assertIn("returning 1 excerpt", automatic_pr_review.reposcout_review_status(evidence))
            self.assertEqual(before, path.read_bytes())

    def test_binary_evidence_requires_all_versions_and_matching_revisions(self):
        pr = {"head": {"sha": "head"}, "base": {"sha": "base"}}
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict("os.environ", {"PR_REVIEW_EVIDENCE_DIR": directory}):
                self.assertEqual(automatic_pr_review.load_binary_evidence(pr), ([], True))
                for version in ("BW1W100", "BW1W110", "BW1W120", "BW1W130", "BW1WCI"):
                    Path(directory, version + ".json").write_text(
                        json.dumps(
                            {"version": version, "head_sha": "head", "base_sha": "base", "limitations": [], "units": []}
                        ),
                        encoding="utf-8",
                    )
                evidence, limited = automatic_pr_review.load_binary_evidence(pr)
                self.assertEqual(len(evidence), 5)
                self.assertFalse(limited)
                pr["head"]["sha"] = "new-head"
                self.assertEqual(automatic_pr_review.load_binary_evidence(pr), ([], True))

    def test_submit_review_uses_github_review_event(self):
        github = GitHub("owner/repository", "token")
        with (
            mock.patch.object(github, "list_reviews", return_value=[]),
            mock.patch.object(github, "request") as request,
            mock.patch.object(github, "remove_legacy_comments"),
        ):
            github.submit_review(7, "head-sha", "REQUEST_CHANGES", "body")
        request.assert_called_once_with(
            "POST",
            "/repos/owner/repository/pulls/7/reviews",
            {"commit_id": "head-sha", "event": "REQUEST_CHANGES", "body": "body"},
        )

    def test_file_pagination_reports_when_the_review_limit_omits_files(self):
        github = GitHub("owner/repository", "token")
        pages = [
            [{"filename": "file-{}".format(index)} for index in range(start, start + 100)] for start in (0, 100, 200)
        ]
        with mock.patch.object(github, "request", side_effect=pages):
            files, truncated = github.list_changed_files(1)
        self.assertEqual(len(files), 200)
        self.assertTrue(truncated)

    def test_rerun_updates_its_existing_review_without_posting_another(self):
        github = GitHub("owner/repository", "token")
        review = {
            "id": 42,
            "user": {"login": "github-actions[bot]"},
            "commit_id": "head-sha",
            "state": "COMMENTED",
            "body": "<!-- bw1-automatic-review --> old findings",
        }
        body = "<!-- bw1-automatic-review --> fresh findings"
        with (
            mock.patch.object(github, "list_reviews", return_value=[review]),
            mock.patch.object(github, "request") as request,
            mock.patch.object(github, "remove_legacy_comments"),
        ):
            github.submit_review(7, "head-sha", "COMMENT", body)
        request.assert_called_once_with(
            "PUT", "/repos/owner/repository/pulls/7/reviews/42", {"body": body}
        )

    def test_unchanged_rerun_does_not_rewrite_its_review(self):
        github = GitHub("owner/repository", "token")
        body = "<!-- bw1-automatic-review --> findings"
        review = {
            "id": 42,
            "user": {"login": "github-actions[bot]"},
            "commit_id": "head-sha",
            "state": "COMMENTED",
            "body": body,
        }
        with (
            mock.patch.object(github, "list_reviews", return_value=[review]),
            mock.patch.object(github, "request") as request,
            mock.patch.object(github, "remove_legacy_comments"),
        ):
            github.submit_review(7, "head-sha", "COMMENT", body)
        request.assert_not_called()

    def test_exact_file_limit_is_not_reported_as_omitted(self):
        github = GitHub("owner/repository", "token")
        pages = [
            [{"filename": "file-{}".format(index)} for index in range(start, start + 100)] for start in (0, 100)
        ] + [[]]
        with mock.patch.object(github, "request", side_effect=pages):
            files, truncated = github.list_changed_files(1)
        self.assertEqual(len(files), 200)
        self.assertFalse(truncated)

    def test_check_run_limit_reports_truncated_coverage(self):
        github = GitHub("owner/repository", "token")
        pages = [
            {"check_runs": [{"name": "check", "status": "completed"} for _ in range(100)]},
            {"check_runs": [{"name": "extra", "status": "completed"}]},
        ]
        with mock.patch.object(github, "request", side_effect=pages):
            checks, truncated = github.list_check_runs("head-sha")
        self.assertEqual(len(checks), automatic_pr_review.MAX_CHECK_RUNS)
        self.assertTrue(truncated)

    def test_source_context_includes_only_changed_source_files(self):
        github = GitHub("owner/repository", "token")
        files = [
            {"filename": "src/example.cpp", "status": "modified"},
            {"filename": "docs/readme.md", "status": "modified"},
        ]
        with mock.patch.object(github, "get_text_file", return_value="source text") as get_file:
            contexts, limited = collect_source_context(github, files, "head-sha")
        self.assertEqual(contexts, [{"path": "src/example.cpp", "status": "complete", "text": "source text"}])
        self.assertEqual(limited, 0)
        get_file.assert_called_once_with("src/example.cpp", "head-sha")

    def test_truncated_source_context_is_reported(self):
        github = GitHub("owner/repository", "token")
        files = [{"filename": "src/example.cpp", "status": "modified"}]
        with (
            mock.patch.object(github, "get_text_file", return_value="source text"),
            mock.patch.object(automatic_pr_review, "MAX_SOURCE_CONTEXT_CHARS", 6),
        ):
            contexts, limited = collect_source_context(github, files, "head-sha")
        self.assertEqual(contexts[0]["status"], "truncated")
        self.assertEqual(contexts[0]["text"], "source")
        self.assertEqual(limited, 1)

    def test_large_configure_file_does_not_hide_cpp_source(self):
        github = GitHub("owner/repository", "token")
        files = [{"filename": "configure.py", "status": "modified"}, {"filename": "src/sky.cpp", "status": "added"}]

        def source(path, ref):
            return "x" * 200_000 if path == "configure.py" else "int value = 37;\n"

        with mock.patch.object(github, "get_text_file", side_effect=source):
            contexts, limited = collect_source_context(github, files, "head", "base")
        self.assertEqual(limited, 0)
        self.assertEqual([c["path"] for c in contexts], ["src/sky.cpp"])
        self.assertTrue(all(c["status"] == "complete" for c in contexts))
        self.assertTrue(contexts[0]["base_comments_complete"])
        self.assertEqual(contexts[0]["base_comment_signatures"], [])

    def test_cpp_is_retained_first_when_source_budget_is_exhausted(self):
        github = GitHub("owner/repository", "token")
        files = [{"filename": "tools/extra.yml", "status": "modified"}, {"filename": "src/sky.cpp", "status": "added"}]
        with (
            mock.patch.object(github, "get_text_file", return_value="int x;\n"),
            mock.patch.object(automatic_pr_review, "MAX_SOURCE_CONTEXT_CHARS", 7),
        ):
            contexts, limited = collect_source_context(github, files, "head")
        self.assertEqual(contexts[0]["path"], "src/sky.cpp")
        self.assertEqual(contexts[0]["status"], "complete")
        self.assertEqual(contexts[1]["status"], "omitted by size limit")
        self.assertEqual(limited, 1)

    def test_cpp_patch_is_retained_before_large_symbol_records(self):
        files = [
            {"filename": "config/BW1W120/symbols.txt", "patch": "s" * 100},
            {"filename": "src/sky.cpp", "patch": "@@ -0,0 +1 @@\n+int x;"},
        ]
        with mock.patch.object(automatic_pr_review, "MAX_TOTAL_PATCH_CHARS", 30):
            context, lines, limited = build_diff_context(files)
        self.assertLess(context.index("src/sky.cpp"), context.index("symbols.txt"))
        self.assertEqual(lines["src/sky.cpp"], {1})
        self.assertEqual(limited, 1)

    def test_all_patches_in_a_sky_sized_change_fit(self):
        files = [
            {"filename": "config/BW1W120/symbols{}.txt".format(i), "patch": "@@ -0,0 +1 @@\n+" + "s" * 14_000}
            for i in range(6)
        ]
        files.append({"filename": "src/sky.cpp", "patch": "@@ -0,0 +1 @@\n+" + "c" * 18_000})
        _, lines, limited = build_diff_context(files)
        self.assertEqual(limited, 0)
        self.assertTrue(all(value == {1} for value in lines.values()))

    def test_excluded_python_does_not_consume_file_budget_or_reach_diff(self):
        github = GitHub("owner/repository", "token")
        excluded = [{"filename": "tools/file{}.py".format(i), "patch": "@@ -0,0 +1 @@\n+# comment"} for i in range(100)]
        cpp = {"filename": "src/sky.cpp", "patch": "@@ -0,0 +1 @@\n+int value;"}
        with mock.patch.object(github, "request", side_effect=[excluded, [cpp]]):
            files, limited = github.list_changed_files(1)
        self.assertEqual(files, [cpp])
        self.assertFalse(limited)
        context, lines, limited = build_diff_context(excluded + [cpp, {"filename": "configure.py", "patch": "hidden"}])
        self.assertEqual(lines, {"src/sky.cpp": {1}})
        self.assertNotIn("tools/file", context)
        self.assertNotIn("configure.py", context)

    def test_excluded_python_is_not_fetched_for_source_context(self):
        github = GitHub("owner/repository", "token")
        files = [{"filename": path} for path in ("configure.py", "tools/test.py", ".claude/skills/demo/run.py")]
        with mock.patch.object(github, "get_text_file") as fetch:
            contexts, limited = collect_source_context(github, files, "head", "base")
        self.assertEqual((contexts, limited), ([], 0))
        fetch.assert_not_called()

    def test_excluded_only_pr_skips_model_and_review_submission(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("guide", "instructions", "event"):
                (root / name).write_text("{}")
            github = mock.MagicMock()
            github.request.return_value = {
                "state": "open",
                "draft": False,
                "head": {"sha": "head"},
                "base": {"sha": "base"},
            }
            github.list_changed_files.return_value = ([{"filename": "tools/helper.py"}], False)
            env = {
                "GITHUB_REPOSITORY": "boltz/bw1-decomp",
                "GITHUB_TOKEN": "test",
                "PR_NUMBER": "1",
                "PR_REVIEW_API_KEY": "test",
                "PR_REVIEW_MODEL": "test",
                "PR_REVIEW_GUIDE": str(root / "guide"),
                "PR_REVIEW_INSTRUCTIONS": str(root / "instructions"),
                "GITHUB_EVENT_PATH": str(root / "event"),
            }
            with (
                mock.patch.dict(automatic_pr_review.os.environ, env),
                mock.patch.object(automatic_pr_review, "GitHub", return_value=github),
                mock.patch.object(automatic_pr_review, "load_binary_evidence", return_value=([], True)),
                mock.patch.object(automatic_pr_review, "call_model") as model,
            ):
                automatic_pr_review.main()
            model.assert_not_called()
            github.submit_review.assert_not_called()

    def test_missing_configure_status_is_unknown(self):
        github = GitHub("owner/repository", "token")
        with mock.patch.object(github, "get_text_file", return_value=None):
            status = collect_configure_status(
                github, [{"filename": "src/example.cpp", "status": "modified"}], "head-sha"
            )
        self.assertEqual(status, [{"source": "example.cpp", "status": "unknown", "entries": []}])

    def test_added_line_numbers_tracks_new_side_only(self):
        patch = "@@ -4,3 +4,4 @@\n context\n-old line\n+new line\n+another line\n tail\n"
        self.assertEqual(added_line_numbers(patch), {5, 6})

    def test_build_diff_context_tracks_only_added_lines(self):
        files = [
            {
                "filename": "src/example.cpp",
                "status": "modified",
                "additions": 1,
                "deletions": 1,
                "patch": "@@ -1 +1 @@\n-old\n+new",
            }
        ]
        context, changed_lines, truncated = build_diff_context(files)
        self.assertIn("src/example.cpp", context)
        self.assertEqual(changed_lines, {"src/example.cpp": {1}})
        self.assertEqual(truncated, 0)

    def test_truncated_patch_cannot_anchor_an_omitted_line(self):
        files = [
            {
                "filename": "src/example.cpp",
                "status": "modified",
                "additions": 2,
                "deletions": 0,
                "patch": "@@ -0,0 +1,2 @@\n+one\n+two\n",
            }
        ]
        with mock.patch.object(automatic_pr_review, "MAX_FILE_PATCH_CHARS", 21):
            _, changed_lines, truncated = build_diff_context(files)
        self.assertEqual(changed_lines, {"src/example.cpp": {1}})
        self.assertEqual(truncated, 1)

    def test_large_cpp_and_symbol_patches_fit_review_limits(self):
        files = [
            {
                "filename": "config/BW1W120/symbols.txt",
                "status": "modified",
                "additions": 1,
                "deletions": 0,
                "patch": "@@ -0,0 +1 @@\n+" + ("s" * 8_900),
            },
            {
                "filename": "src/Lionhead/LH3DLib/development/LH3DMeshIntersect.cpp",
                "status": "added",
                "additions": 1,
                "deletions": 0,
                "patch": "@@ -0,0 +1 @@\n+" + ("c" * 26_900),
            },
        ]
        _, changed_lines, limited = build_diff_context(files)
        self.assertEqual(limited, 0)
        self.assertEqual(changed_lines[files[0]["filename"]], {1})
        self.assertEqual(changed_lines[files[1]["filename"]], {1})

    def test_missing_patch_is_reported_as_limited_coverage(self):
        files = [
            {
                "filename": "assets/image.bin",
                "status": "modified",
                "additions": 0,
                "deletions": 0,
                "patch": None,
            }
        ]
        _, changed_lines, limited = build_diff_context(files)
        self.assertEqual(changed_lines, {"assets/image.bin": set()})
        self.assertEqual(limited, 1)

    def test_findings_must_reference_added_lines(self):
        result = {
            "findings": [
                {
                    "path": "src/example.cpp",
                    "line": 9,
                    "function": "",
                    "severity": "high",
                    "classification": "correctness defect",
                    "title": "Out-of-bounds access",
                    "evidence": "The index is unchecked.",
                    "assumptions": "",
                    "why_it_matters": "It can read past the buffer.",
                    "suggestion": "Validate the index.",
                    "matching_effect": "",
                    "source_linking": "",
                    "checks": "",
                    "unresolved_decision": "",
                },
                {
                    "path": "src/example.cpp",
                    "line": 8,
                    "function": "",
                    "severity": "high",
                    "classification": "correctness defect",
                    "title": "Not an added line",
                    "evidence": "No evidence.",
                    "assumptions": "",
                    "why_it_matters": "No reason.",
                    "suggestion": "No change.",
                    "matching_effect": "",
                    "source_linking": "",
                    "checks": "",
                    "unresolved_decision": "",
                },
            ]
        }
        findings, invalid_count, omitted_count = valid_findings(
            result, {"src/example.cpp": {9}}, {"src/example.cpp": ""}
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["line"], 9)
        self.assertEqual(invalid_count, 1)
        self.assertEqual(omitted_count, 0)

    def test_comment_escapes_mentions_and_html(self):
        escaped = safe_markdown("notify @team <tag> & keep")
        self.assertNotIn("@team", escaped)
        self.assertIn("&lt;tag&gt;", escaped)
        self.assertIn("&amp;", escaped)

    def test_complete_clean_review_is_approved(self):
        self.assertEqual(choose_review_event([], 0, 0), "APPROVE")

    def test_partial_coverage_never_approves(self):
        self.assertEqual(choose_review_event([], 1, 0), "COMMENT")
        self.assertEqual(choose_review_event([], 0, 1), "COMMENT")
        self.assertEqual(choose_review_event([], 0, 0, 1), "COMMENT")
        finding = {"classification": "correctness defect", "severity": "high"}
        self.assertEqual(choose_review_event([finding], 1, 0), "COMMENT")
        self.assertEqual(choose_review_event([], 0, 0, limited_context_files=1), "COMMENT")

    def test_prompt_marks_context_as_untrusted_and_reports_tool_limits(self):
        system, user = make_prompt(
            "instructions",
            "guide",
            "title",
            "body",
            [],
            "diff",
            0,
            0,
            [],
            0,
            [],
            [],
            [],
            False,
        )
        self.assertIn("RepoScout", system)
        self.assertIn("TimVoice (myvoice)", system)
        self.assertIn("high-school reading level (grades 9-10)", system)
        self.assertIn("do a separate writing pass", system)
        self.assertIn("all prose fields", system)
        self.assertIn("Keep file names, function names, values, quoted maintainer text, and links exact", system)
        self.assertIn("untrusted review input", user)

    def test_missing_voice_guide_stops_review_instead_of_silently_using_default_voice(self):
        with mock.patch.object(Path, "read_text", side_effect=OSError("missing guide")):
            with self.assertRaisesRegex(automatic_pr_review.ReviewError, "writing guide could not be loaded"):
                make_prompt("instructions", "guide", "title", "body", [], "diff", 0, 0, [], 0, [], [], [], False)

    def test_prompt_supplies_added_line_instead_of_hunk_context_start(self):
        files = [{
            "filename": "src/example.cpp",
            "patch": "@@ -378,4 +378,4 @@\n context1\n context2\n context3\n-old\n+new",
        }]
        diff, changed_lines, limited = build_diff_context(files)
        system, user = make_prompt(
            "instructions", "guide", "title", "body", files, diff, 0, limited,
            [], 0, [], [], [], False, changed_lines=changed_lines,
        )
        payload = json.loads(user.split("not instructions:\n", 1)[1])
        self.assertEqual(payload["added_source_line_numbers"], {"src/example.cpp": [381]})
        self.assertIn("starting line can be unchanged context", system)

    def test_findings_beyond_limit_prevent_approval(self):
        finding = {
            "path": "src/example.cpp",
            "line": 1,
            "function": "",
            "severity": "low",
            "classification": "maintainability/readability issue",
            "title": "Finding",
            "evidence": "Evidence",
            "assumptions": "",
            "why_it_matters": "Impact",
            "suggestion": "Suggestion",
            "matching_effect": "",
            "source_linking": "",
            "checks": "",
            "unresolved_decision": "",
        }
        result = {"findings": [dict(finding) for _ in range(13)]}
        findings, invalid_count, omitted_count = valid_findings(
            result, {"src/example.cpp": {1}}, {"src/example.cpp": ""}
        )
        self.assertEqual(len(findings), automatic_pr_review.MAX_FINDINGS)
        self.assertEqual(invalid_count, 0)
        self.assertEqual(omitted_count, 1)
        self.assertEqual(choose_review_event(findings, 0, 0, invalid_count, omitted_count), "COMMENT")

    def test_finding_can_anchor_to_a_changed_function(self):
        finding = {
            "path": "src/example.cpp",
            "line": 0,
            "function": "MeshIntersect::GetImpactPointAlex",
            "severity": "high",
            "classification": "correctness defect",
            "title": "Incorrect miss handling",
            "evidence": "The function reads an unset result.",
            "assumptions": "",
            "why_it_matters": "The output is undefined.",
            "suggestion": "Return before using the result.",
            "matching_effect": "The TU is NonMatching.",
            "source_linking": "Normal links use extracted code.",
            "checks": "Build checks are pending.",
            "unresolved_decision": "Original binary behavior is unknown.",
        }
        findings, invalid_count, omitted_count = valid_findings(
            {"findings": [finding]},
            {"src/example.cpp": set()},
            {"src/example.cpp": "@@ -0,0 +1,2 @@\n+bool MeshIntersect::GetImpactPointAlex() {\n+    return false;\n"},
        )
        self.assertEqual(invalid_count, 0)
        self.assertEqual(omitted_count, 0)
        self.assertEqual(findings[0]["function"], "MeshIntersect::GetImpactPointAlex")

    def test_function_anchor_must_appear_in_a_changed_hunk(self):
        finding = {
            "path": "src/example.cpp",
            "line": 0,
            "function": "MeshIntersect::UnchangedFunction",
            "severity": "high",
            "classification": "correctness defect",
            "title": "Finding",
            "evidence": "Evidence",
            "assumptions": "",
            "why_it_matters": "Impact",
            "suggestion": "Suggestion",
            "matching_effect": "",
            "source_linking": "",
            "checks": "",
            "unresolved_decision": "",
        }
        findings, invalid_count, _ = valid_findings(
            {"findings": [finding]},
            {"src/example.cpp": set()},
            {"src/example.cpp": "@@ -4 +4 @@\n+changed line\n"},
        )
        self.assertEqual(findings, [])
        self.assertEqual(invalid_count, 1)

    def test_correctness_findings_request_changes(self):
        findings = [{"classification": "correctness defect", "severity": "medium"}]
        self.assertEqual(choose_review_event(findings, 0, 0), "REQUEST_CHANGES")

    def test_other_findings_are_comments(self):
        findings = [{"classification": "unconfirmed risk", "severity": "high"}]
        self.assertEqual(choose_review_event(findings, 0, 0), "COMMENT")

    def test_no_finding_review_body_is_advisory(self):
        body = make_review_body([], "0123456789abcdef", "APPROVE", 0, 0)
        self.assertIn("No changes needed in the code reviewed", body)
        self.assertIn("Maintainers decide whether to merge", body)

    def test_requested_changes_are_visible_before_the_scorecard(self):
        body = make_review_body([], "head", "COMMENT", 0, 0)
        self.assertLess(body.index("## Changes requested"), body.index("## Review scorecard"))
        self.assertIn("No confirmed code edits are listed", body)
        self.assertIn("That does not mean the PR is ready to merge", body)

    def test_change_checklist_separates_fixes_preferences_and_risks(self):
        findings = [
            {"path": "src/sky.cpp", "line": 4, "classification": kind,
             "suggestion": action, "why_it_matters": "Explain the reason."}
            for kind, action in (("maintainability/readability issue", "Remove unused header LH3DRender.h."),
                                 ("stylistic preference", "Consider a shorter name."),
                                 ("unconfirmed risk", "Check the original branch before changing it."))
        ]
        body = "\n".join(render_requested_changes(findings, None, "boltz/bw1-decomp", "head"))
        changes, rest = body.split("## Optional suggestions")
        optional, investigation = rest.split("## Needs investigation")
        self.assertIn("- [ ]", changes)
        self.assertIn("Remove unused header LH3DRender.h.", changes)
        self.assertIn("/blob/head/src/sky.cpp#L4", changes)
        self.assertNotIn("Check the original", changes)
        self.assertIn("Consider a shorter name.", optional)
        self.assertIn("not instructions to change behavior", investigation)
        self.assertIn("Check the original branch", investigation)

    def test_quality_checklist_includes_each_kind_of_action(self):
        location = {"path": "src/sky.cpp", "line": 4}
        quality = {
            "bad": [dict(location, suggestion="Remove unused LH3DRender.h.", reason="It is unused.")],
            "magic": [dict(location, suggestion="Use the existing count.", reason="This is a count.")],
            "uncertain": [dict(location, literal="0", reason="The argument type is missing.")],
            "inventory": {"comments": [dict(location, kind="remove prose comment", text="new explanation")],
                          "limitations": [], "comments_complete": True},
            "invalid": 0, "numbers_complete": False,
        }
        body = "\n".join(render_requested_changes([], quality, "", "head"))
        changes, investigation = body.split("## Needs investigation")
        self.assertIn("Remove unused LH3DRender.h.", changes)
        self.assertIn("Use the existing count.", changes)
        self.assertIn("Remove this added prose comment.", changes)
        self.assertNotIn("argument type is missing", changes)
        self.assertIn("argument type is missing", investigation)

    def test_review_timestamp_uses_eastern_daylight_and_standard_time(self):
        for month, expected in ((7, "2026-07-15 08:30:00 AM EDT"), (1, "2026-01-15 07:30:00 AM EST")):
            with self.subTest(month=month), mock.patch.object(automatic_pr_review, "datetime") as clock:
                instant = datetime(2026, month, 15, 12, 30, tzinfo=timezone.utc)
                clock.now.side_effect = lambda zone: instant.astimezone(zone)
                body = make_review_body([], "0123456789abcdef", "COMMENT", 0, 0)
            self.assertEqual(body.splitlines()[1], "Reviewed: {} (Eastern Time)".format(expected))

    def test_review_body_reports_unreviewed_overflow(self):
        body = make_review_body([], "0123456789abcdef", "COMMENT", 0, 0, 0, 1)
        self.assertIn("not enough to finish this review", body)
        self.assertIn("more issue(s) did not fit", body)

    def test_responses_api_text_extraction_skips_non_message_items(self):
        envelope = {
            "output": [
                {"type": "reasoning", "summary": []},
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": '{"findings": []}'}],
                },
            ]
        }
        self.assertEqual(response_output_text(envelope), '{"findings": []}')

    def test_responses_api_text_extraction_accepts_top_level_text(self):
        self.assertEqual(response_output_text({"output_text": '{"findings": []}'}), '{"findings": []}')

    def test_model_retries_empty_and_malformed_responses(self):
        def response(envelope):
            result = mock.MagicMock()
            result.read.return_value = json.dumps(envelope).encode("utf-8")
            result.__enter__.return_value = result
            return result

        responses = [
            response({"output": [{"type": "reasoning"}]}),
            response({"output_text": "not JSON"}),
            response({"output_text": '{"findings": [], "quality": {}}'}),
        ]
        opener = mock.MagicMock()
        opener.open.side_effect = responses
        with (
            mock.patch.object(automatic_pr_review.urllib.request, "build_opener", return_value=opener),
            mock.patch.object(automatic_pr_review.time, "sleep"),
        ):
            result = call_model("https://example.test/v1", "token", "model", "system", "user")
        self.assertEqual(result, {"findings": [], "quality": {}})
        self.assertEqual(opener.open.call_count, 3)


if __name__ == "__main__":
    unittest.main()
