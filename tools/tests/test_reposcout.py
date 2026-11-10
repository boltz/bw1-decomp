import json
import tempfile
import unittest
from pathlib import Path

from tools.reposcout import connect, replace_repository_data, retrieve, status


class RetrievalIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = connect(Path(self.tmp.name) / "index.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_indexes_only_merged_and_returns_citations_and_metadata(self):
        pulls = [
            {
                "number": 12,
                "title": "Creature: match planner",
                "body": "Verified 100% in BW1W120.",
                "merged_at": "2026-01-02T00:00:00Z",
                "updated_at": "2026-01-02T00:00:00Z",
                "html_url": "https://github.com/openblack/bw1-decomp/pull/12",
                "user": {"login": "dev"},
                "merged_by": {"login": "reviewer"},
                "author_association": "CONTRIBUTOR",
                "base": {"ref": "main"},
                "head": {"ref": "match/planner"},
            },
            {"number": 13, "title": "Open planner idea", "body": "unmerged", "merged_at": None},
        ]
        docs = [
            {
                "id": "r#12:review:2",
                "repository": "r",
                "pr_number": 12,
                "kind": "review",
                "title": "",
                "body": "Please keep the CreaturePlan helper local.",
                "author": "reviewer",
                "author_association": "MEMBER",
                "state": "APPROVED",
                "path": "src/Creature.cpp",
                "line": 88,
                "created_at": "2026-01-01",
                "updated_at": "2026-01-01",
                "html_url": "https://github.com/review/2",
                "raw_json": json.dumps({"id": 2}),
            }
        ]
        result = replace_repository_data(
            self.db,
            "r",
            pulls,
            docs,
            [(12, {"filename": "src/CreaturePlan.cpp", "status": "modified", "additions": 4, "deletions": 1})],
        )
        self.assertEqual(result["merged_pulls"], 1)
        found = retrieve(self.db, "CreaturePlan local", repository="r")
        self.assertEqual(found["result_count"], 1)
        row = found["results"][0]
        self.assertEqual(row["pr_number"], 12)
        self.assertEqual(row["author_association"], "MEMBER")
        self.assertEqual(row["url"], "https://github.com/review/2")
        self.assertEqual(row["pr_url"], "https://github.com/openblack/bw1-decomp/pull/12")
        self.assertIn("precedent, not proof", found["source_policy"])
        file_result = retrieve(self.db, "CreaturePlan.cpp", repository="r")
        self.assertEqual(file_result["results"][0]["kind"], "changed_file")
        self.assertEqual(file_result["results"][0]["path"], "src/CreaturePlan.cpp")

    def test_repository_snapshot_replacement_removes_stale_content(self):
        pull = {
            "number": 1,
            "title": "old phrase",
            "body": "old body",
            "merged_at": "now",
            "user": {},
            "html_url": "https://github.com/r/pull/1",
        }
        replace_repository_data(self.db, "r", [pull], [], [])
        replace_repository_data(self.db, "r", [], [], [])
        self.assertEqual(retrieve(self.db, "old phrase", repository="r")["result_count"], 0)

    def test_status_counts_document_kinds(self):
        pull = {
            "number": 1,
            "title": "Alpha",
            "body": "body",
            "merged_at": "now",
            "user": {},
            "html_url": "https://github.com/r/pull/1",
        }
        doc = {
            "id": "r#1:pr",
            "repository": "r",
            "pr_number": 1,
            "kind": "pull_request",
            "title": "Alpha",
            "body": "body",
            "raw_json": "{}",
            "author": "dev",
            "html_url": "https://github.com/r/pull/1",
        }
        replace_repository_data(self.db, "r", [pull], [doc], [])
        self.assertEqual(status(self.db, "r")["merged_pulls"], 1)
        self.assertEqual(status(self.db, "r")["documents_by_kind"]["pull_request"], 1)

    def test_query_text_cannot_inject_fts_syntax(self):
        self.assertEqual(retrieve(self.db, 'title OR body "', repository="r")["result_count"], 0)


class DiscussionRetrievalTests(unittest.TestCase):
    def test_discussion_filter_prefers_recorded_repository_relationship_without_promoting_merge_status(self):
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / "index.sqlite3")
            pull = {
                "number": 1,
                "title": "readability",
                "body": "readability",
                "merged_at": "now",
                "user": {},
                "html_url": "https://github.com/r/pull/1",
            }
            docs = [
                {
                    "id": "pr",
                    "repository": "r",
                    "pr_number": 1,
                    "kind": "pull_request",
                    "title": "readability",
                    "body": "readability",
                    "raw_json": "{}",
                },
                {
                    "id": "other",
                    "repository": "r",
                    "pr_number": 1,
                    "kind": "review",
                    "title": "",
                    "body": "readability",
                    "author_association": "CONTRIBUTOR",
                    "state": "APPROVED",
                    "raw_json": "{}",
                },
                {
                    "id": "member",
                    "repository": "r",
                    "pr_number": 1,
                    "kind": "inline_review_comment",
                    "title": "",
                    "body": "readability",
                    "author_association": "MEMBER",
                    "raw_json": "{}",
                },
            ]
            for doc in docs:
                doc["html_url"] = "https://github.com/r/pull/1#" + doc["id"]
            replace_repository_data(db, "r", [pull], docs, [])
            result = retrieve(db, "readability", repository="r", discussions_only=True)
            self.assertEqual(len(result["results"]), 2)
            self.assertEqual(result["results"][0]["author_association"], "MEMBER")
            self.assertIsNone(result["results"][0]["review_state"])
            self.assertNotIn("pull_request", [row["kind"] for row in result["results"]])
            db.close()


if __name__ == "__main__":
    unittest.main()
