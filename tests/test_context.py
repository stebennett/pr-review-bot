"""Context pack assembly. No network: checkouts are built locally with tarfile."""

import pathlib
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import review  # noqa: E402


def make_tree(root: pathlib.Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content.encode() if isinstance(content, str) else content)


def make_archive(dest: pathlib.Path, top: str, files: dict[str, str]) -> pathlib.Path:
    """A GitHub-shaped tarball: one top-level owner-repo-sha directory."""
    staging = dest / "staging" / top
    staging.mkdir(parents=True)
    make_tree(staging, files)
    archive = dest / "src.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(staging, arcname=top)
    return archive


class TestBudgets(unittest.TestCase):
    def test_shares_sum_to_one(self):
        self.assertAlmostEqual(sum(review.CONTEXT_SHARES.values()), 1.0, places=6)

    def test_every_part_has_a_share(self):
        self.assertEqual(
            set(review.CONTEXT_SHARES),
            {"changed_files", "call_sites", "conventions", "requirements", "tree"},
        )

    def test_budgets_never_exceed_the_total(self):
        self.assertLessEqual(sum(review.budgets(83000).values()), 83000)

    def test_the_changed_files_share_is_the_largest(self):
        b = review.budgets(83000)
        self.assertEqual(max(b, key=b.get), "changed_files")

    def test_a_smaller_total_scales_every_part_down(self):
        small, large = review.budgets(8300), review.budgets(83000)
        for part in review.CONTEXT_SHARES:
            self.assertLess(small[part], large[part])

    def test_a_negative_or_zero_total_never_yields_a_negative_budget(self):
        for total in (-100, -1, 0):
            with self.subTest(total=total):
                for value in review.budgets(total).values():
                    self.assertGreaterEqual(value, 0)


class TestAccounting(unittest.TestCase):
    def test_text_within_budget_passes_through_unchanged(self):
        acc = review.Accounting({"tree": 100})
        self.assertEqual(acc.add("tree", "short"), "short")

    def test_text_over_budget_is_truncated_with_a_marker(self):
        acc = review.Accounting({"tree": 40})
        out = acc.add("tree", "x" * 200)
        self.assertLessEqual(len(out), 40)
        self.assertIn("truncated", out)

    def test_usage_is_recorded_per_part(self):
        acc = review.Accounting({"tree": 100, "conventions": 100})
        acc.add("tree", "abc")
        self.assertEqual(acc.used["tree"], 3)
        self.assertEqual(acc.used["conventions"], 0)

    def test_truncated_output_never_exceeds_its_limit(self):
        # 0 and 5 are too small to fit even a shortened marker; 40 fits a short
        # marker but not the full one; 5000 is a realistic per-part budget.
        for limit in (0, 5, 40, 5000):
            with self.subTest(limit=limit):
                acc = review.Accounting({"tree": limit})
                out = acc.add("tree", "x" * 10000)
                self.assertLessEqual(len(out), limit)

    def test_used_matches_the_returned_length_when_truncated(self):
        acc = review.Accounting({"tree": 40})
        out = acc.add("tree", "x" * 200)
        self.assertEqual(acc.used["tree"], len(out))

    def test_every_limit_from_0_to_80_stays_within_budget_and_is_marked(self):
        # Swept, not hand-picked: this is exactly the range (roughly 0-15) where
        # the tiered-marker fallback used to go silent instead of shrinking the
        # marker further, and neighbouring values (16-80) must keep working too.
        for limit in range(0, 81):
            with self.subTest(limit=limit):
                acc = review.Accounting({"tree": limit})
                out = acc.add("tree", "CONTENT" * 100)
                self.assertLessEqual(len(out), limit)
                if limit >= 1:
                    self.assertIn(
                        "…", out, f"limit={limit} produced no truncation marker at all"
                    )

    def test_a_negative_limit_behaves_exactly_like_zero(self):
        for limit in (-1, -100):
            with self.subTest(limit=limit):
                acc = review.Accounting({"tree": limit})
                out = acc.add("tree", "x" * 200)
                self.assertEqual(out, "")
                self.assertEqual(acc.used["tree"], 0)

    def test_text_within_budget_is_never_marked_as_truncated(self):
        acc = review.Accounting({"tree": 100})
        out = acc.add("tree", "well within budget")
        self.assertEqual(out, "well within budget")
        self.assertNotIn("…", out)
        self.assertEqual(acc.truncated, set())


class TestExtractCheckout(unittest.TestCase):
    def test_the_top_level_directory_is_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            archive = make_archive(tmp, "owner-repo-abc123", {"src/foo.py": "print(1)\n"})
            root = review.extract_checkout(archive, tmp / "out")
            self.assertIsNotNone(root)
            self.assertEqual((root / "src" / "foo.py").read_text(), "print(1)\n")

    def test_a_path_traversal_entry_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            evil = tmp / "evil.txt"
            evil.write_text("pwned")
            archive = tmp / "evil.tar.gz"
            with tarfile.open(archive, "w:gz") as tf:
                tf.add(evil, arcname="../escaped.txt")
            self.assertIsNone(review.extract_checkout(archive, tmp / "out"))
            self.assertFalse((tmp / "escaped.txt").exists())

    def test_a_corrupt_archive_returns_none_rather_than_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            bad = tmp / "bad.tar.gz"
            bad.write_bytes(b"not a tarball at all")
            self.assertIsNone(review.extract_checkout(bad, tmp / "out"))


class TestStreamCapped(unittest.TestCase):
    class FakeResponse:
        def __init__(self, payload: bytes, chunk: int = 8):
            self._data, self._chunk = payload, chunk
            self._pos = 0

        def read(self, n):
            out = self._data[self._pos:self._pos + min(n, self._chunk)]
            self._pos += len(out)
            return out

    def test_a_payload_under_the_cap_is_written_whole(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = pathlib.Path(tmp) / "out.bin"
            self.assertTrue(review.stream_capped(self.FakeResponse(b"a" * 50), dest, 1000))
            self.assertEqual(dest.read_bytes(), b"a" * 50)

    def test_a_payload_over_the_cap_aborts_and_removes_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = pathlib.Path(tmp) / "out.bin"
            self.assertFalse(review.stream_capped(self.FakeResponse(b"a" * 5000), dest, 100))
            self.assertFalse(dest.exists())


class _FakeGH:
    """A GitHub stand-in whose tarball is a real, valid archive on disk."""

    def __init__(self, archive_path: pathlib.Path):
        self._archive_path = archive_path

    def open_tarball(self, repo, sha):
        return open(self._archive_path, "rb")


class TestBuildContext(unittest.TestCase):
    def _pr(self, sha="abc123def"):
        return {"number": 1, "title": "t", "body": "the PR body", "head": {"sha": sha}}

    def test_a_malformed_max_context_chars_degrades_rather_than_raising(self):
        cfg = dict(review.DEFAULTS)
        cfg["max_context_chars"] = "oops-not-an-int"
        with tempfile.TemporaryDirectory() as tmp:
            with review.build_context(
                None, "o/r", self._pr(), "", cfg, enabled=True, worktree=tmp
            ) as ctx:
                pass
        self.assertEqual(ctx.pack, "")
        self.assertTrue(
            any("context assembly failed" in note for note in ctx.notes),
            f"expected a 'context assembly failed' note, got {ctx.notes!r}",
        )

    def test_a_malformed_max_context_chars_leaves_no_temp_checkout_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            archive = make_archive(tmp, "owner-repo-abc123de", {"src/foo.py": "print(1)\n"})
            gh = _FakeGH(archive)
            cfg = dict(review.DEFAULTS)
            cfg["max_context_chars"] = "oops-not-an-int"

            system_tmp = pathlib.Path(tempfile.gettempdir())
            before = set(system_tmp.glob("pr-reviewer-*"))
            with review.build_context(gh, "owner/repo", self._pr(), "", cfg, enabled=True) as ctx:
                self.assertEqual(ctx.pack, "")
            after = set(system_tmp.glob("pr-reviewer-*"))
            self.assertEqual(before, after)

    def test_context_disabled_yields_an_empty_pack_with_exactly_one_note(self):
        # Nothing else in this suite exercises build_context/Context directly;
        # this is the cheapest path through it (no checkout, no accounting).
        cfg = dict(review.DEFAULTS)
        with review.build_context(None, "o/r", self._pr(), "", cfg, enabled=False) as ctx:
            pass
        self.assertEqual(ctx.pack, "")
        self.assertEqual(ctx.notes, ["context disabled"])
        self.assertIsNone(ctx.root)

    def test_a_worktree_populates_the_pack_with_real_changed_file_content(self):
        # This is the actual wiring pack_changed_files -> build_context: nothing
        # else in this suite exercises it end to end, and build_context's own
        # broad except means a wiring bug here would otherwise degrade silently
        # to an empty pack rather than raise.
        diff = (
            "diff --git a/src/foo.py b/src/foo.py\n"
            "--- a/src/foo.py\n"
            "+++ b/src/foo.py\n"
            "@@ -1,2 +1,2 @@\n"
            " alpha\n"
            "-beta\n"
            "+beta2\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            make_tree(tmp, {"src/foo.py": "alpha\nbeta2\ngamma\n"})
            cfg = dict(review.DEFAULTS)
            with review.build_context(
                None, "o/r", self._pr(), diff, cfg, enabled=True, worktree=str(tmp)
            ) as ctx:
                pass
        self.assertIn("src/foo.py", ctx.pack)
        # Whole-file inclusion is rendered through windowed() too, so every
        # line — including ones a whole-file fit never used to number — comes
        # out with its real line number and no elision marker (it is the
        # entire file).
        self.assertIn("1: alpha\n2: beta2\n3: gamma", ctx.pack)
        self.assertNotIn("elided", ctx.pack)
        self.assertEqual(ctx.notes, [])


class TestPathMatches(unittest.TestCase):
    PATTERNS = ["*.lock", "package-lock.json", "**/generated/**"]

    def test_a_suffix_pattern_matches_at_any_depth(self):
        self.assertTrue(review.path_matches("deps/Cargo.lock", self.PATTERNS))

    def test_an_exact_name_matches_at_any_depth(self):
        self.assertTrue(review.path_matches("web/package-lock.json", self.PATTERNS))

    def test_a_double_star_pattern_matches_an_interior_directory(self):
        self.assertTrue(review.path_matches("src/generated/api.py", self.PATTERNS))

    def test_an_ordinary_source_file_does_not_match(self):
        self.assertFalse(review.path_matches("src/foo.py", self.PATTERNS))


class TestIsBinary(unittest.TestCase):
    def test_text_is_not_binary(self):
        self.assertFalse(review.is_binary(b"def main():\n    pass\n"))

    def test_a_null_byte_means_binary(self):
        self.assertTrue(review.is_binary(b"PNG\x00\x01\x02"))


class TestMergeRanges(unittest.TestCase):
    def test_padding_widens_a_single_range(self):
        self.assertEqual(review.merge_ranges([(50, 60)], 10), [(40, 70)])

    def test_padding_never_runs_below_line_one(self):
        self.assertEqual(review.merge_ranges([(2, 3)], 10), [(1, 13)])

    def test_overlapping_padded_ranges_merge(self):
        self.assertEqual(review.merge_ranges([(10, 12), (20, 22)], 10), [(1, 32)])

    def test_distant_ranges_stay_separate(self):
        self.assertEqual(review.merge_ranges([(10, 12), (500, 502)], 5), [(5, 17), (495, 507)])


class TestWindowed(unittest.TestCase):
    TEXT = "\n".join(f"line{i}" for i in range(1, 101))

    def test_a_window_carries_line_numbers(self):
        out = review.windowed(self.TEXT, [(3, 5)])
        self.assertIn("3: line3", out)
        self.assertIn("5: line5", out)

    def test_content_outside_the_window_is_absent(self):
        out = review.windowed(self.TEXT, [(3, 5)])
        self.assertNotIn("line50", out)

    def test_elision_between_windows_states_how_much_was_cut(self):
        out = review.windowed(self.TEXT, [(1, 2), (90, 91)])
        self.assertIn("87 lines elided", out)

    def test_a_full_span_needs_no_elision_marker(self):
        out = review.windowed(self.TEXT, [(1, 100)])
        self.assertNotIn("elided", out)


class TestPackChangedFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.cfg = dict(review.DEFAULTS)
        self.addCleanup(self.tmp.cleanup)

    def acc(self, limit=40000):
        return review.Accounting({"changed_files": limit, "call_sites": 1, "conventions": 1,
                                  "requirements": 1, "tree": 1})

    def test_a_small_file_is_included_whole(self):
        make_tree(self.root, {"src/foo.py": "alpha\nbeta\ngamma\n"})
        out = review.pack_changed_files(
            self.root, None, "o/r", "sha", {"src/foo.py": [(1, 3)]}, self.cfg, self.acc())
        self.assertIn("src/foo.py", out)
        self.assertIn("beta", out)

    def test_an_ignored_path_is_skipped(self):
        make_tree(self.root, {"Cargo.lock": "noise\n"})
        out = review.pack_changed_files(
            self.root, None, "o/r", "sha", {"Cargo.lock": [(1, 1)]}, self.cfg, self.acc())
        self.assertNotIn("noise", out)

    def test_a_binary_file_is_skipped(self):
        make_tree(self.root, {"img.png": "PNG\x00\x01"})
        out = review.pack_changed_files(
            self.root, None, "o/r", "sha", {"img.png": [(1, 1)]}, self.cfg, self.acc())
        self.assertNotIn("PNG", out)

    def test_a_file_over_the_hard_size_cap_is_skipped(self):
        make_tree(self.root, {"huge.py": "x\n" * 300_000})
        out = review.pack_changed_files(
            self.root, None, "o/r", "sha", {"huge.py": [(1, 1)]}, self.cfg, self.acc())
        self.assertIn("skipped", out)

    def test_a_missing_file_does_not_raise(self):
        out = review.pack_changed_files(
            self.root, None, "o/r", "sha", {"gone.py": [(1, 1)]}, self.cfg, self.acc())
        self.assertIsInstance(out, str)

    def test_the_file_cap_names_what_was_dropped(self):
        files = {f"src/f{i}.py": f"body{i}\n" for i in range(30)}
        make_tree(self.root, files)
        ranges = {p: [(1, 1)] for p in files}
        out = review.pack_changed_files(
            self.root, None, "o/r", "sha", ranges, self.cfg, self.acc())
        # Distinct from files excluded by ignore_paths (Finding 3): this is the
        # file-count cap, so the label says so.
        self.assertIn("### 5 further changed file(s) not shown (file cap)", out)
        # All 30 paths tie on hunk count (one range each), so the cap breaks
        # the tie alphabetically on path — assert exactly which 5 lost that
        # tiebreak, not just that some count of them did.
        expected_dropped = {"src/f5.py", "src/f6.py", "src/f7.py", "src/f8.py", "src/f9.py"}
        self.assertEqual(expected_dropped, set(sorted(files)[25:]))
        for path in expected_dropped:
            self.assertIn(f"- {path}", out)
        for path in set(files) - expected_dropped:
            self.assertNotIn(f"- {path}", out)

    def test_files_with_more_hunks_are_preferred(self):
        make_tree(self.root, {"busy.py": "b\n", "quiet.py": "q\n"})
        ranges = {"quiet.py": [(1, 1)], "busy.py": [(1, 1), (5, 6), (9, 10)]}
        cfg = dict(self.cfg, max_context_files=1)
        out = review.pack_changed_files(self.root, None, "o/r", "sha", ranges, cfg, self.acc())
        self.assertIn("1: b", out)                                  # busy.py's contents, numbered
        self.assertNotIn("quiet.py\n```", out)                      # quiet.py's body never rendered
        self.assertIn("### 1 further changed file(s) not shown (file cap)", out)

    def test_the_section_never_overruns_its_budget_regardless_of_file_count(self):
        # Regression guard for the divide-and-floor defect: per_file used to
        # floor at 2000 chars regardless of how many files shared the budget,
        # so 20+ files (well inside the 25-file cap) blew the section's total
        # past its limit and Accounting hard-truncated mid-file. The greedy,
        # remaining-budget-aware assembly must never let that happen again,
        # at any file count on either side of the old failure threshold.
        body = "\n".join(f"line{i}" for i in range(1, 301)) + "\n"  # ~2100 chars whole
        for n in (1, 5, 19, 20, 25, 30):
            with self.subTest(n=n):
                tmp = tempfile.TemporaryDirectory()
                try:
                    root = pathlib.Path(tmp.name)
                    files = {f"src/f{i}.py": body for i in range(n)}
                    make_tree(root, files)
                    ranges = {p: [(150, 151)] for p in files}
                    acc = self.acc()
                    out = review.pack_changed_files(
                        root, None, "o/r", "sha", ranges, self.cfg, acc)
                    self.assertLessEqual(len(out), acc.limits["changed_files"])
                    self.assertNotIn("changed_files", acc.truncated)
                finally:
                    tmp.cleanup()

    def test_a_file_larger_than_its_cap_is_windowed_rather_than_dropped_whole(self):
        lines = "\n".join(f"line{i}" for i in range(1, 501))  # 500 lines
        make_tree(self.root, {"big.py": lines + "\n"})
        acc = self.acc(limit=3000)  # deliberately tight changed_files budget
        out = review.pack_changed_files(
            self.root, None, "o/r", "sha", {"big.py": [(250, 251)]}, self.cfg, acc)
        self.assertIn("elided", out)
        self.assertIn("250: line250", out)
        self.assertIn("251: line251", out)
        self.assertNotIn("line1\n", out)  # far outside the window, must be elided

    def test_ignored_and_cap_dropped_files_get_distinct_trailer_labels(self):
        files = {f"src/f{i}.py": f"body{i}\n" for i in range(3)}
        files["Cargo.lock"] = "noise\n"
        make_tree(self.root, files)
        ranges = {p: [(1, 1)] for p in files}
        cfg = dict(self.cfg, max_context_files=2)
        out = review.pack_changed_files(self.root, None, "o/r", "sha", ranges, cfg, self.acc())
        # "Cargo.lock" sorts before the src/f*.py files, so it is the sole
        # ignore_paths exclusion; the file cap then drops the lowest-priority
        # remaining file. Both must be named, under their own distinct label.
        self.assertIn("### 1 file(s) excluded by ignore_paths\n- Cargo.lock", out)
        self.assertIn("### 1 further changed file(s) not shown (file cap)\n- src/f2.py", out)

    def test_max_context_files_zero_or_negative_yields_no_file_bodies(self):
        make_tree(self.root, {"src/foo.py": "alpha\nbeta\ngamma\n"})
        for limit in (0, -1):
            with self.subTest(limit=limit):
                cfg = dict(self.cfg, max_context_files=limit)
                out = review.pack_changed_files(
                    self.root, None, "o/r", "sha", {"src/foo.py": [(1, 3)]}, cfg, self.acc())
                self.assertNotIn("beta", out)
                self.assertIn("### 1 further changed file(s) not shown (file cap)\n- src/foo.py", out)

    def test_whole_file_and_windowed_output_are_both_line_numbered(self):
        make_tree(self.root, {"small.py": "alpha\nbeta\ngamma\n"})
        out_whole = review.pack_changed_files(
            self.root, None, "o/r", "sha", {"small.py": [(1, 3)]}, self.cfg, self.acc())
        self.assertIn("1: alpha", out_whole)
        self.assertIn("2: beta", out_whole)
        self.assertIn("3: gamma", out_whole)
        self.assertNotIn("elided", out_whole)  # the window IS the whole file

        lines = "\n".join(f"line{i}" for i in range(1, 501))
        make_tree(self.root, {"big.py": lines + "\n"})
        out_windowed = review.pack_changed_files(
            self.root, None, "o/r", "sha", {"big.py": [(250, 251)]}, self.cfg, self.acc(limit=3000))
        self.assertIn("250: line250", out_windowed)
        self.assertIn("251: line251", out_windowed)


if __name__ == "__main__":
    unittest.main()
