import json
import tempfile
import unittest
from pathlib import Path

from tools import bw1_progress_tracker as tracker


def measures(code=50):
    return {
        "total_code": 100, "matched_code": code, "matched_code_percent": float(code),
        "total_data": 40, "matched_data": 20, "matched_data_percent": 50.0,
        "total_functions": 10, "matched_functions": 5,
        "total_units": 4, "complete_units": 2,
        "complete_code": 30, "complete_code_percent": 30.0,
        "complete_data": 10, "complete_data_percent": 25.0,
    }


def metadata(conclusion="success", bad_version=None):
    jobs = [{"name": f"build ({version})", "conclusion": "failure" if version == bad_version else "success"}
            for version in tracker.VERSIONS]
    return {"headSha": "a" * 40, "headBranch": "main", "event": "push",
            "createdAt": "2026-10-31T00:00:00Z", "conclusion": conclusion, "jobs": jobs}


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.reports = self.root / "download"
        for version in tracker.VERSIONS:
            path = self.reports / f"{version}_report" / "report.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"version": 2, "measures": measures(), "units": [], "categories": []}))

    def test_complete_run_archives_immutable_reports_and_renders(self):
        meta = tracker.inspect_metadata(metadata(), "openblack/bw1-decomp", 42)
        first = tracker.archive_run(self.root / "data", meta, self.reports)
        self.assertEqual(first["status"], "archived")
        self.assertEqual(len(first["manifest"]["versions"]), 5)
        self.assertEqual(tracker.archive_run(self.root / "data", meta, self.reports)["status"], "already_archived")
        self.assertEqual(tracker.verify_archive(self.root / "data")["reports_verified"], 5)
        site = tracker.render(self.root / "data", self.root / "site", "openblack/bw1-decomp")
        self.assertEqual(site["runs"], 1)
        self.assertIn("50.00%", (self.root / "site" / "index.html").read_text())
        self.assertIn("BW1W120 code", (self.root / "site" / "BW1W120-code.svg").read_text())

    def test_reingest_rejects_changed_artifact_bytes(self):
        meta = tracker.inspect_metadata(metadata(), "openblack/bw1-decomp", 47)
        tracker.archive_run(self.root / "data", meta, self.reports)
        path = self.reports / "BW1W120_report" / "report.json"
        path.write_text(path.read_text() + " ")
        with self.assertRaisesRegex(tracker.TrackerError, "changed BW1W120"):
            tracker.archive_run(self.root / "data", meta, self.reports)

    def test_archive_verification_detects_corruption(self):
        meta = tracker.inspect_metadata(metadata(), "openblack/bw1-decomp", 48)
        tracker.archive_run(self.root / "data", meta, self.reports)
        path = self.root / "data" / "runs" / "openblack__bw1-decomp" / "48" / "BW1W120.json"
        path.write_text(path.read_text() + " ")
        with self.assertRaisesRegex(tracker.TrackerError, "hash differs"):
            tracker.verify_archive(self.root / "data")

    def test_summary_only_archive_keeps_small_manifests(self):
        meta = tracker.inspect_metadata(metadata(), "boltz/bw1-decomp", 49)
        tracker.archive_run(self.root / "data", meta, self.reports, summary_only=True)
        root = self.root / "data" / "runs" / "boltz__bw1-decomp" / "49"
        self.assertFalse((root / "BW1W120.json").exists())
        self.assertEqual(tracker.verify_archive(self.root / "data")["summary_only_records"], 5)
        self.assertEqual(tracker.render(self.root / "data", self.root / "site", "boltz/bw1-decomp")["latest_run"], 49)

    def test_failed_checksum_or_missing_job_cannot_be_archived(self):
        for raw in (metadata(conclusion="failure", bad_version="BW1W100"),
                    metadata(conclusion="success", bad_version="BW1W100")):
            with self.subTest(raw=raw):
                meta = tracker.inspect_metadata(raw, "openblack/bw1-decomp", 43)
                self.assertFalse(meta["eligible"])
                with self.assertRaises(tracker.TrackerError):
                    tracker.archive_run(self.root / "data", meta, self.reports)
        self.assertEqual(tracker.all_manifests(self.root / "data"), [])

    def test_missing_report_rejected_without_partial_snapshot(self):
        (self.reports / "BW1WCI_report" / "report.json").unlink()
        meta = tracker.inspect_metadata(metadata(), "openblack/bw1-decomp", 44)
        with self.assertRaises(tracker.TrackerError):
            tracker.archive_run(self.root / "data", meta, self.reports)
        self.assertEqual(tracker.all_manifests(self.root / "data"), [])

    def test_comparison_uses_byte_deltas_and_rejects_cross_repo(self):
        old = tracker.archive_run(self.root / "data", tracker.inspect_metadata(metadata(), "openblack/bw1-decomp", 45), self.reports)["manifest"]
        for version in tracker.VERSIONS:
            path = self.reports / f"{version}_report" / "report.json"
            value = json.loads(path.read_text())
            value["measures"] = measures(60)
            path.write_text(json.dumps(value))
        new = tracker.archive_run(self.root / "data", tracker.inspect_metadata(metadata(), "openblack/bw1-decomp", 46), self.reports)["manifest"]
        self.assertEqual(tracker.compare_runs(old, new)["versions"]["BW1W120"]["matched_code_bytes"], 10)
        new["repository"] = "another/repo"
        with self.assertRaises(tracker.TrackerError):
            tracker.compare_runs(old, new)


if __name__ == "__main__":
    unittest.main()
