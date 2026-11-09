import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from matched_readability_review import review_items
from readability_scope import select_scope
from test_readability_scope import entity, review, scope
from readability_review import DIMENSIONS
import review_quality


class ReviewTests(unittest.TestCase):
    def test_pending_or_empty_scope_never_calls_model(self):
        def unexpected(*args):
            self.fail("Model must not be called")
        for selected in (scope([], []), scope([], [entity(match="unverified")])):
            result, details = review_items(selected, Path("unused"), "rules", "guide", unexpected)
            self.assertIsNone(result["score"])
            self.assertEqual(details, [])

    def test_numeric_inventory_uses_whole_selected_function_not_only_diff(self):
        files = [dict(filename="src/a.cpp", additions=1, patch="@@ -3 +3 @@\n-old\n+new")]
        sources = [dict(path="src/a.cpp", status="complete", text="int f() {\nreturn 27;\n}\nint bad=999;\n",
                        base_comment_signatures=[], base_comments_complete=True)]
        inventory = review_quality.inventory(files, sources, base_context_required=True,
                                             scored_ranges={"src/a.cpp": {1, 2, 3}})
        self.assertEqual([number["literal"] for number in inventory["numbers"]], ["27"])

    def test_full_item_review_uses_selected_source_only(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            (repo / "src").mkdir()
            (repo / "src/a.cpp").write_text("void clear_name() {}\nvoid excluded_unmatched() { int ugly=9876; }\n")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
            sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
            item = entity()
            item["ranges"] = [dict(path="src/a.cpp", start=1, end=1, role="definition", text="void clear_name() {}\n")]
            selected = scope([], [item])
            selected.update(base=sha, head=sha)
            def model(system, user):
                self.assertNotIn("excluded_unmatched", user)
                self.assertNotIn("9876", user)
                self.assertIn("clear_name", user)
                return dict(findings=[], quality=dict(dimensions={name: 20 for name in DIMENSIONS},
                    rationale="Clear role", lionhead_context="Compatible style", precedent_summary="No precedent supplied",
                    good=[dict(path="src/a.cpp", line=1, reason="Clear name", suggestion="")], bad=[], precedents=[],
                    numbers_reviewed=True, numeric_decisions=[]))
            result, details = review_items(selected, repo, "rubric", "guide", model)
            self.assertEqual(result["score"], 100)
            self.assertTrue(result["complete"])


if __name__ == "__main__":
    unittest.main()
