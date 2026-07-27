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


class TestDiffAnchors(unittest.TestCase):
    def test_added_lines_anchor_on_the_right(self):
        anchors = review.diff_anchors(TWO_FILES)
        self.assertIn(("src/bar.py", 2, "RIGHT"), anchors)

    def test_removed_lines_anchor_on_the_left(self):
        anchors = review.diff_anchors(DELETED_FILE)
        self.assertIn(("src/gone.py", 1, "LEFT"), anchors)
        self.assertIn(("src/gone.py", 2, "LEFT"), anchors)

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


if __name__ == "__main__":
    unittest.main()
