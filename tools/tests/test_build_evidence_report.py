import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools import build_evidence_report as report
from tools import automatic_pr_review as reviewer


class BuildReportTests(unittest.TestCase):
    def test_exact_binary_limits_are_separate_from_successful_jobs(self):
        evidence = [{"version": "BW1W120", "units": [{}], "limitations": [
            "Unit limit: 8 of 4682 selected units included", "sky disassembly truncated",
            "data disassembly failed: error: Function not found: .*",
        ]}]
        body = report.render_report("boltz/bw1-decomp", "abcdef", {"id": 4, "conclusion": "success"},
                                    [{"name": "build (BW1W120)", "conclusion": "success"}], evidence, True)
        self.assertIn("| build (BW1W120) | success |", body)
        self.assertIn("Unit limit: 8 of 4682", body)
        self.assertIn("sky disassembly truncated", body)
        self.assertIn("data-only unit", body)
        self.assertIn("BW1WCI: no usable artifact", body)
        self.assertIn("not a missing readability result", body)
        self.assertIn("does not approve or merge", body)

    def test_failed_build_cannot_be_presented_as_matching_success(self):
        body = report.render_report("boltz/bw1-decomp", "head", {"id": 4, "conclusion": "failure"}, [], [], True)
        self.assertIn("The build did not succeed", body)
        self.assertIn("Job results | unavailable", body)

    def test_superseded_build_does_not_post(self):
        env = {"GITHUB_REPOSITORY": "boltz/bw1-decomp", "PR_NUMBER": "19", "BUILD_RUN_ID": "4",
               "PR_REVIEW_EXPECTED_SHA": "old", "GITHUB_TOKEN": "test"}
        github = mock.MagicMock()
        github.request.return_value = {"state": "open", "head": {"sha": "new"}}
        with mock.patch.dict(os.environ, env), mock.patch.object(report, "GitHub", return_value=github):
            report.main()
        self.assertEqual(github.request.call_count, 1)

    def test_report_rejects_mismatched_build_run(self):
        env = {"GITHUB_REPOSITORY": "boltz/bw1-decomp", "PR_NUMBER": "19", "BUILD_RUN_ID": "4",
               "PR_REVIEW_EXPECTED_SHA": "head", "GITHUB_TOKEN": "test"}
        github = mock.MagicMock()
        github.request.side_effect = [{"state": "open", "head": {"sha": "head"}},
                                      {"event": "push", "status": "completed", "head_sha": "head"}]
        with mock.patch.dict(os.environ, env), mock.patch.object(report, "GitHub", return_value=github):
            with self.assertRaises(reviewer.ReviewError):
                report.main()

    def test_report_rerun_updates_its_own_comment_without_formal_approval(self):
        env = {"GITHUB_REPOSITORY": "boltz/bw1-decomp", "PR_NUMBER": "19", "BUILD_RUN_ID": "4",
               "PR_REVIEW_EXPECTED_SHA": "head", "GITHUB_TOKEN": "test"}
        pr = {"state": "open", "head": {"sha": "head"}, "base": {"sha": "base"}}
        run = {"id": 4, "event": "pull_request", "status": "completed", "head_sha": "head",
               "conclusion": "success", "head_repository": {"full_name": "boltz/bw1-decomp"}}
        existing = {"id": 8, "user": {"login": "github-actions[bot]"},
                    "body": report.MARKER + " https://github.com/boltz/bw1-decomp/actions/runs/4"}
        github = mock.MagicMock()
        github.request.side_effect = [pr, run, {"jobs": []}, [existing], pr, {}]
        with (mock.patch.dict(os.environ, env), mock.patch.object(report, "GitHub", return_value=github),
              mock.patch.object(report, "load_binary_evidence", return_value=([], True))):
            report.main()
        call = github.request.call_args
        self.assertEqual(call.args[:2], ("PATCH", "/repos/boltz/bw1-decomp/issues/comments/8"))
        self.assertIn("Build and binary evidence", call.args[2]["body"])
        github.submit_review.assert_not_called()


class ParallelReviewTests(unittest.TestCase):
    def test_readability_review_does_not_wait_for_build_evidence_or_approve(self):
        from tools.tests.test_review_quality import quality, inventory
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("guide", "instructions", "event"):
                (root / name).write_text("{}")
            github = mock.MagicMock()
            github.request.return_value = {"state": "open", "draft": False,
                                            "head": {"sha": "head"}, "base": {"sha": "base"}}
            github.list_changed_files.return_value = ([{"filename": "src/example.cpp", "patch": "@@ -0,0 +1 @@\n+void F();"}], False)
            raw = quality()
            raw.update(good=[{"path": "src/example.cpp", "line": 1, "reason": "The declaration is simple.", "suggestion": "Keep it."}], numeric_decisions=[])
            inv = inventory("void F();")
            env = {"GITHUB_REPOSITORY": "boltz/bw1-decomp", "GITHUB_TOKEN": "test", "PR_NUMBER": "19",
                   "PR_REVIEW_API_KEY": "test", "PR_REVIEW_MODEL": "test", "PR_REVIEW_PHASE": "readability",
                   "PR_REVIEW_GUIDE": str(root / "guide"), "PR_REVIEW_INSTRUCTIONS": str(root / "instructions"),
                   "GITHUB_EVENT_PATH": str(root / "event"), "PR_REVIEW_QUALITY_REPORT": str(root / "quality.json")}
            with (mock.patch.dict(os.environ, env), mock.patch.object(reviewer, "GitHub", return_value=github),
                  mock.patch.object(reviewer, "load_binary_evidence") as binary,
                  mock.patch.object(reviewer, "collect_reposcout_evidence", return_value={}),
                  mock.patch.object(reviewer, "collect_source_context", return_value=([], 0)),
                  mock.patch.object(reviewer, "collect_configure_status", return_value=[]),
                  mock.patch.object(reviewer.review_quality, "inventory", return_value=inv),
                  mock.patch.object(reviewer, "call_model", return_value={"findings": [], "quality": raw})):
                reviewer.main()
            binary.assert_not_called()
            github.list_check_runs.assert_not_called()
            args = github.submit_review.call_args.args
            self.assertEqual(args[2], "COMMENT")
            self.assertIn("## Readability review", args[3])
            self.assertIn("reported separately after Build finishes", args[3])
            self.assertNotIn("Missing or incomplete code and build results", args[3])

    def test_workflows_start_independently_and_execute_trusted_code(self):
        import yaml
        root = Path(__file__).resolve().parents[2]
        early = yaml.load((root / ".github/workflows/automatic-review.yml").read_text(), Loader=yaml.BaseLoader)
        later = yaml.load((root / ".github/workflows/build-evidence-report.yml").read_text(), Loader=yaml.BaseLoader)
        self.assertIn("pull_request_target", early["on"])
        self.assertNotIn("workflow_run", early["on"])
        self.assertEqual(later["on"]["workflow_run"]["workflows"], ["Build"])
        for workflow in (early, later):
            self.assertNotIn("needs", workflow["jobs"]["review"])
            checkout = workflow["jobs"]["review"]["steps"][0]
            self.assertEqual(checkout["with"]["ref"], "${{ github.workflow_sha }}")
        self.assertFalse(any("binary evidence" in step.get("name", "").lower()
                             for step in early["jobs"]["review"]["steps"]))
