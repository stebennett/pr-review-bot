"""Diff parsing. Pure functions — no network, no filesystem, no model."""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import review  # noqa: E402

TWO_FILES = """\
diff --git a/src/foo.py b/src/foo.py
index 1111111..2222222 100644
--- a/src/foo.py
+++ b/src/foo.py
@@ -10,5 +10,6 @@ def existing():
 context_one
 context_two
-removed_line
+added_line
+another_added
 context_three
 context_four
diff --git a/src/bar.py b/src/bar.py
index 3333333..4444444 100644
--- a/src/bar.py
+++ b/src/bar.py
@@ -1,2 +1,3 @@
 alpha
+beta
 gamma
"""

NEW_FILE = """\
diff --git a/src/new.py b/src/new.py
new file mode 100644
index 0000000..5555555
--- /dev/null
+++ b/src/new.py
@@ -0,0 +1,2 @@
+first
+second
"""

DELETED_FILE = """\
diff --git a/src/gone.py b/src/gone.py
deleted file mode 100644
index 6666666..0000000
--- a/src/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-was_one
-was_two
"""

# A hunkless rename sits between two hunk-bearing files. It has no `--- `/`+++ `
# lines at all, so only a `diff --git ` handler that closes the pending hunk
# stops src/a.py's hunk from swallowing `similarity index …`/`rename from …`/
# `rename to …` as if they were context lines.
RENAME_BETWEEN = """\
diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -1,2 +1,2 @@
 alpha
-beta
+gamma
diff --git a/src/old_b.py b/src/new_b.py
similarity index 100%
rename from src/old_b.py
rename to src/new_b.py
diff --git a/src/c.py b/src/c.py
--- a/src/c.py
+++ b/src/c.py
@@ -1,1 +1,1 @@
-zeta
+eta
"""

# Same shape, but the hunkless entry is a binary file instead of a rename.
BINARY_BETWEEN = """\
diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -1,2 +1,2 @@
 alpha
-beta
+gamma
diff --git a/img/x.png b/img/x.png
index 1234567..89abcde 100644
Binary files a/img/x.png and b/img/x.png differ
diff --git a/src/c.py b/src/c.py
--- a/src/c.py
+++ b/src/c.py
@@ -1,1 +1,1 @@
-zeta
+eta
"""

# `\ No newline at end of file` is neither a `+`, `-`, nor context line and must
# not consume a line number on either side.
NO_NEWLINE = """\
diff --git a/src/nl.py b/src/nl.py
index 1111111..2222222 100644
--- a/src/nl.py
+++ b/src/nl.py
@@ -1,2 +1,2 @@
 context
-old_line
\\ No newline at end of file
+new_line
\\ No newline at end of file
"""


class TestDiffPaths(unittest.TestCase):
    def test_every_changed_path_is_found(self):
        self.assertEqual(sorted(review.diff_paths(TWO_FILES)), ["src/bar.py", "src/foo.py"])

    def test_right_side_ranges_cover_the_hunk(self):
        # foo.py's hunk starts at new-file line 10; six of its seven body lines
        # consume a RIGHT-side line number (the removed one does not).
        self.assertEqual(review.diff_paths(TWO_FILES)["src/foo.py"], [(10, 15)])

    def test_a_new_file_is_included(self):
        self.assertEqual(review.diff_paths(NEW_FILE), {"src/new.py": [(1, 2)]})

    def test_a_deleted_file_has_no_right_side_range(self):
        self.assertEqual(review.diff_paths(DELETED_FILE), {})

    def test_an_empty_diff_yields_nothing(self):
        self.assertEqual(review.diff_paths(""), {})

    def test_a_hunkless_rename_between_two_files_does_not_leak_into_either(self):
        # Regression: `diff --git ` must close a pending hunk. Without that,
        # src/a.py's hunk swallows the rename's metadata lines as context,
        # inflating its range past its real two body lines.
        self.assertEqual(
            review.diff_paths(RENAME_BETWEEN),
            {"src/a.py": [(1, 2)], "src/c.py": [(1, 1)]},
        )

    def test_a_hunkless_binary_entry_between_two_files_does_not_leak_into_either(self):
        self.assertEqual(
            review.diff_paths(BINARY_BETWEEN),
            {"src/a.py": [(1, 2)], "src/c.py": [(1, 1)]},
        )

    def test_no_newline_marker_does_not_extend_the_range(self):
        # Regression: a line starting with `\` is neither `+`, `-`, nor context
        # and must not consume a line number on either side.
        self.assertEqual(review.diff_paths(NO_NEWLINE), {"src/nl.py": [(1, 2)]})


class TestDiffAnchors(unittest.TestCase):
    def test_added_lines_anchor_on_the_right(self):
        anchors = review.diff_anchors(TWO_FILES)
        self.assertIn(("src/bar.py", 2, "RIGHT"), anchors)

    def test_removed_lines_anchor_on_the_left(self):
        # Full equality, not membership: DELETED_FILE has exactly two lines,
        # both removed, so this also catches any over-generation.
        anchors = review.diff_anchors(DELETED_FILE)
        self.assertEqual(
            anchors,
            {("src/gone.py", 1, "LEFT"), ("src/gone.py", 2, "LEFT")},
        )

    def test_context_lines_anchor_on_both_sides(self):
        anchors = review.diff_anchors(TWO_FILES)
        self.assertIn(("src/bar.py", 1, "RIGHT"), anchors)
        self.assertIn(("src/bar.py", 1, "LEFT"), anchors)

    def test_a_line_outside_every_hunk_is_not_an_anchor(self):
        anchors = review.diff_anchors(TWO_FILES)
        self.assertNotIn(("src/foo.py", 500, "RIGHT"), anchors)

    def test_a_path_not_in_the_diff_is_not_an_anchor(self):
        anchors = review.diff_anchors(TWO_FILES)
        self.assertNotIn(("src/untouched.py", 1, "RIGHT"), anchors)

    def test_hunk_header_and_file_header_lines_are_not_anchors(self):
        # '+++ b/path' starts with '+' and must not be mistaken for an added line.
        anchors = review.diff_anchors(NEW_FILE)
        self.assertEqual(anchors, {("src/new.py", 1, "RIGHT"), ("src/new.py", 2, "RIGHT")})

    def test_a_hunkless_rename_between_two_files_yields_no_bogus_anchors(self):
        anchors = {a for a in review.diff_anchors(RENAME_BETWEEN) if a[0] == "src/a.py"}
        self.assertEqual(
            anchors,
            {
                ("src/a.py", 1, "RIGHT"),
                ("src/a.py", 1, "LEFT"),
                ("src/a.py", 2, "LEFT"),
                ("src/a.py", 2, "RIGHT"),
            },
        )

    def test_a_hunkless_binary_entry_between_two_files_yields_no_bogus_anchors(self):
        anchors = {a for a in review.diff_anchors(BINARY_BETWEEN) if a[0] == "src/a.py"}
        self.assertEqual(
            anchors,
            {
                ("src/a.py", 1, "RIGHT"),
                ("src/a.py", 1, "LEFT"),
                ("src/a.py", 2, "LEFT"),
                ("src/a.py", 2, "RIGHT"),
            },
        )

    def test_no_newline_marker_yields_no_anchor_of_its_own(self):
        self.assertEqual(
            review.diff_anchors(NO_NEWLINE),
            {
                ("src/nl.py", 1, "RIGHT"),
                ("src/nl.py", 1, "LEFT"),
                ("src/nl.py", 2, "LEFT"),
                ("src/nl.py", 2, "RIGHT"),
            },
        )


def _finding(path, line, side="RIGHT"):
    return {
        "path": path, "line": line, "side": side, "severity": "blocking",
        "claim": "c", "consequence": "q", "failure_scenario": None,
        "fix": "f", "addressed_prior": False,
    }


class TestAnchorViolations(unittest.TestCase):
    def envelope(self, lens, findings):
        return {"lens": lens, "status": "complete", "findings": findings, "notes": "n"}

    def test_a_finding_inside_the_diff_is_not_a_violation(self):
        env = [self.envelope("craft", [_finding("src/bar.py", 2)])]
        self.assertEqual(review.anchor_violations(env, TWO_FILES), [])

    def test_a_finding_on_an_untouched_line_is_a_violation(self):
        finding = _finding("src/bar.py", 900)
        env = [self.envelope("craft", [finding])]
        self.assertEqual(review.anchor_violations(env, TWO_FILES), [("craft", finding)])

    def test_a_finding_on_an_untouched_file_is_a_violation(self):
        finding = _finding("src/elsewhere.py", 1)
        env = [self.envelope("craft", [finding])]
        self.assertEqual(review.anchor_violations(env, TWO_FILES), [("craft", finding)])

    def test_the_side_is_part_of_the_anchor_key(self):
        # bar.py has three RIGHT lines but only two LEFT ones, so RIGHT 3 is a
        # valid anchor and LEFT 3 is not.
        anchors = review.diff_anchors(TWO_FILES)
        self.assertIn(("src/bar.py", 3, "RIGHT"), anchors)
        finding = _finding("src/bar.py", 3, side="LEFT")
        env = [self.envelope("craft", [finding])]
        self.assertEqual(review.anchor_violations(env, TWO_FILES), [("craft", finding)])

    def test_the_offending_lens_is_reported_with_the_finding(self):
        finding = _finding("nope.py", 1)
        env = [self.envelope("correctness", [finding])]
        self.assertEqual(review.anchor_violations(env, TWO_FILES), [("correctness", finding)])

    def test_a_needs_input_envelope_with_no_findings_is_fine(self):
        env = [{"lens": "craft", "status": "needs-input", "findings": [], "notes": "failed"}]
        self.assertEqual(review.anchor_violations(env, TWO_FILES), [])

    def test_violations_are_reported_across_multiple_lenses_and_findings(self):
        # Full-equality check across a mixed panel: one lens clean, one lens with
        # one good and one bad finding, in the order envelopes/findings appear —
        # guards against both missing and spurious entries.
        good = _finding("src/bar.py", 2)
        bad = _finding("src/bar.py", 900)
        env = [
            self.envelope("requirements", [good]),
            self.envelope("craft", [good, bad]),
        ]
        self.assertEqual(review.anchor_violations(env, TWO_FILES), [("craft", bad)])


if __name__ == "__main__":
    unittest.main()
