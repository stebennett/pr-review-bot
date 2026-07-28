"""Context pack assembly. No network: checkouts are built locally with tarfile."""

import os
import pathlib
import re
import subprocess
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


def unclosed_fence(text: str) -> str | None:
    """The markdown fence `text` leaves open, or None if it is balanced.

    Deliberately an independent implementation of `review._open_fence`, so a
    mutation of that function cannot make the property tests below agree with
    it. Fences are tracked by run *length*, the way CommonMark does, never by
    counting "```" occurrences: an opener may carry an info string, a closer may
    not, a closer must be at least as long as the opener, and only one fence is
    ever open at a time (lines inside a fence are literal text, so a shorter
    fence line inside a longer block opens nothing).
    """
    open_run = 0
    for line in text.split("\n"):
        stripped = line.lstrip(" ")
        if len(line) - len(stripped) > 3 or not stripped.startswith("```"):
            continue
        run = len(stripped) - len(stripped.lstrip("`"))
        rest = stripped[run:]
        if "`" in rest:
            continue                                  # not a fence line at all
        if open_run == 0:
            open_run = run                             # an info string is fine here
        elif run >= open_run and not rest.strip():
            open_run = 0
    return "`" * open_run if open_run else None


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

    def test_a_read_only_filesystem_degrades_rather_than_failing_the_review(self):
        # I1: the never-fail-a-review guarantee used to begin at the pack
        # assembly `try`, leaving the checkout acquisition above it bare — so a
        # hardened pod with a read-only root filesystem, or a full disk, failed
        # *every* review of every pass rather than reviewing with a thin pack.
        def refuse(*a, **k):
            raise OSError(30, "Read-only file system")

        with tempfile.TemporaryDirectory() as tmp:
            archive = make_archive(
                pathlib.Path(tmp), "owner-repo-abc123de", {"src/foo.py": "print(1)\n"})
            gh = _FakeGH(archive)
            real = tempfile.TemporaryDirectory
            tempfile.TemporaryDirectory = refuse
            try:
                with review.build_context(
                    gh, "owner/repo", self._pr(), "", dict(review.DEFAULTS), enabled=True
                ) as ctx:
                    pass
            finally:
                tempfile.TemporaryDirectory = real

        self.assertEqual(ctx.pack, "")
        self.assertIsNone(ctx.root)
        self.assertTrue(
            any("Read-only file system" in note for note in ctx.notes),
            f"expected the real reason in the notes, got {ctx.notes!r}",
        )

    def test_a_config_missing_max_tarball_bytes_degrades_rather_than_raising(self):
        # Reproduced separately from max_context_chars: this KeyError is raised
        # above the old guard, the other below it.
        with tempfile.TemporaryDirectory() as tmp:
            archive = make_archive(
                pathlib.Path(tmp), "owner-repo-abc123de", {"src/foo.py": "print(1)\n"})
            cfg = dict(review.DEFAULTS)
            del cfg["max_tarball_bytes"]
            with review.build_context(
                _FakeGH(archive), "owner/repo", self._pr(), "", cfg, enabled=True
            ) as ctx:
                pass
        self.assertEqual(ctx.pack, "")
        self.assertTrue(any("context assembly failed" in n for n in ctx.notes), ctx.notes)

    def test_a_checkout_validity_check_that_raises_still_yields_a_context(self):
        # The third unguarded call: _checkout_matches_diff walks the diff and
        # touches the filesystem, and either can raise.
        def boom(root, diff):
            raise OSError("stat failed")

        real = review._checkout_matches_diff
        review._checkout_matches_diff = boom
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with review.build_context(
                    None, "o/r", self._pr(), "", dict(review.DEFAULTS),
                    enabled=True, worktree=tmp,
                ) as ctx:
                    pass
        finally:
            review._checkout_matches_diff = real
        self.assertEqual(ctx.pack, "")
        self.assertTrue(any("stat failed" in n for n in ctx.notes), ctx.notes)

    def test_a_body_exception_is_never_swallowed_by_the_pack_guard(self):
        # The guard stops at `yield ctx` on purpose: widening it over the yield
        # would turn a failed review into a context note and a clean exit.
        with self.assertRaises(RuntimeError):
            with tempfile.TemporaryDirectory() as tmp:
                with review.build_context(
                    None, "o/r", self._pr(), "", dict(review.DEFAULTS),
                    enabled=True, worktree=tmp,
                ):
                    raise RuntimeError("the review itself failed")

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

    def test_a_truncated_conventions_document_still_ends_with_a_balanced_fence(self):
        # Round-3-fix regression: a fence-unaware character cut can land
        # inside an open code fence, after which everything build_context
        # appends afterwards (here, "## Path tree (pruned)") would read as
        # quoted content. Swept across three budgets so this does not hinge
        # on one lucky threshold.
        diff = (
            "diff --git a/src/foo.py b/src/foo.py\n"
            "--- a/src/foo.py\n"
            "+++ b/src/foo.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new\n"
        )
        doc = "# Title\n\n```\nexample\n```\n\n" + "filler " * 2000
        for max_chars in (3000, 2800, 2600):
            with self.subTest(max_chars=max_chars):
                with tempfile.TemporaryDirectory() as tmp:
                    tmp = pathlib.Path(tmp)
                    make_tree(tmp, {"src/foo.py": "new\n", "CLAUDE.md": doc})
                    cfg = dict(review.DEFAULTS)
                    cfg["max_context_chars"] = max_chars
                    with review.build_context(
                        None, "o/r", self._pr(), diff, cfg, enabled=True, worktree=str(tmp)
                    ) as ctx:
                        pass
                fence = "````"  # the doc's own longest run is 3, so its wrapper is 4
                self.assertEqual(ctx.pack.count(fence), 2)
                start = ctx.pack.index(fence) + len(fence)
                end = ctx.pack.index(fence, start)
                after_conventions = ctx.pack[end + len(fence):]
                self.assertIn("## Path tree (pruned)", after_conventions)
                # The truncation is still visible in-band, just not fence-breaking.
                self.assertIn("truncated", ctx.pack)

    def test_a_root_containing_a_changed_path_is_accepted_unchanged(self):
        # The positive case: a worktree that plausibly is this repo must be
        # used exactly as before — no note, full pack.
        diff = (
            "diff --git a/src/foo.py b/src/foo.py\n"
            "--- a/src/foo.py\n"
            "+++ b/src/foo.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            make_tree(tmp, {"src/foo.py": "new\n", "CLAUDE.md": "Root rules.\n"})
            cfg = dict(review.DEFAULTS)
            with review.build_context(
                None, "o/r", self._pr(), diff, cfg, enabled=True, worktree=str(tmp)
            ) as ctx:
                pass
        self.assertEqual(ctx.root, tmp.resolve())
        self.assertEqual(ctx.notes, [])
        self.assertIn("src/foo.py", ctx.pack)
        self.assertIn("Root rules.", ctx.pack)

    def test_a_root_matching_none_of_the_diffs_changed_paths_degrades_to_no_checkout(self):
        # The exact scenario from the finding: a real, unrelated directory
        # (e.g. --worktree pointed at /tmp) must not be trusted just because
        # is_dir() is true.
        diff = (
            "diff --git a/src/foo.py b/src/foo.py\n"
            "--- a/src/foo.py\n"
            "+++ b/src/foo.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            make_tree(tmp, {"totally/unrelated/thing.py": "x = 1\n", "CLAUDE.md": "Unrelated rules.\n"})
            cfg = dict(review.DEFAULTS)
            with review.build_context(
                None, "o/r", self._pr(), diff, cfg, enabled=True, worktree=str(tmp)
            ) as ctx:
                pass
        self.assertIsNone(ctx.root)
        self.assertTrue(
            any("matches none of the diff" in note for note in ctx.notes),
            f"expected a degrade note, got {ctx.notes!r}",
        )
        self.assertNotIn("totally/unrelated", ctx.pack)
        self.assertNotIn("## Path tree (pruned)", ctx.pack)
        self.assertNotIn("## Repo conventions", ctx.pack)
        self.assertNotIn("Unrelated rules.", ctx.pack)

    def test_a_deletion_only_diff_against_an_unrelated_root_degrades_via_build_context(self):
        # Round-4 fix, exercised end-to-end: before the fix, collecting
        # new_path (always None for a deletion) made a deletion-only diff
        # match unconditionally, so this scenario silently produced
        # confident wrong context with no note.
        diff = (
            "diff --git a/gone.py b/gone.py\n"
            "deleted file mode 100644\n"
            "--- a/gone.py\n"
            "+++ /dev/null\n"
            "@@ -1,1 +0,0 @@\n"
            "-content\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            make_tree(tmp, {"totally/unrelated/thing.py": "x = 1\n", "CLAUDE.md": "Unrelated rules.\n"})
            cfg = dict(review.DEFAULTS)
            with review.build_context(
                None, "o/r", self._pr(), diff, cfg, enabled=True, worktree=str(tmp)
            ) as ctx:
                pass
        self.assertIsNone(ctx.root)
        self.assertTrue(
            any("matches none of the diff" in note for note in ctx.notes),
            f"expected a degrade note, got {ctx.notes!r}",
        )
        self.assertNotIn("totally/unrelated", ctx.pack)
        self.assertNotIn("## Path tree (pruned)", ctx.pack)
        self.assertNotIn("## Repo conventions", ctx.pack)
        self.assertNotIn("Unrelated rules.", ctx.pack)

    def test_a_root_missing_only_a_diffs_brand_new_files_is_still_accepted(self):
        # The mostly-new-files edge case: a PR that only adds new files gives
        # no changed path that must already exist anywhere, so a merely
        # stale-but-correct checkout (it has the rest of the repo, just not
        # yet this PR's brand-new file) must not be rejected on that basis.
        diff = (
            "diff --git a/src/new_thing.py b/src/new_thing.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/src/new_thing.py\n"
            "@@ -0,0 +1,1 @@\n"
            "+brand new content\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            make_tree(tmp, {"README.md": "hi\n", "src/existing.py": "x = 1\n"})
            cfg = dict(review.DEFAULTS)
            with review.build_context(
                None, "o/r", self._pr(), diff, cfg, enabled=True, worktree=str(tmp)
            ) as ctx:
                pass
        self.assertEqual(ctx.root, tmp.resolve())
        self.assertFalse(any("matches none of the diff" in note for note in ctx.notes))


class TestCheckoutMatchesDiff(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_a_root_with_a_modified_files_path_matches(self):
        make_tree(self.root, {"src/foo.py": "new\n"})
        diff = (
            "diff --git a/src/foo.py b/src/foo.py\n"
            "--- a/src/foo.py\n"
            "+++ b/src/foo.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new\n"
        )
        self.assertTrue(review._checkout_matches_diff(self.root, diff))

    def test_a_root_without_the_modified_files_path_does_not_match(self):
        make_tree(self.root, {"totally/unrelated/thing.py": "x = 1\n"})
        diff = (
            "diff --git a/src/foo.py b/src/foo.py\n"
            "--- a/src/foo.py\n"
            "+++ b/src/foo.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new\n"
        )
        self.assertFalse(review._checkout_matches_diff(self.root, diff))

    def test_a_rename_with_modification_matches_a_correct_pre_rename_checkout(self):
        # Round-4 fix: the check must collect the *old* path, not the new
        # one. A checkout that genuinely is this repo, just not yet at a
        # commit that renamed the file, has old/path.py and not
        # new/path.py — it must not be falsely rejected for that.
        make_tree(self.root, {"old/path.py": "old content\n"})
        diff = (
            "diff --git a/old/path.py b/new/path.py\n"
            "similarity index 90%\n"
            "rename from old/path.py\n"
            "rename to new/path.py\n"
            "--- a/old/path.py\n"
            "+++ b/new/path.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old content\n"
            "+new content\n"
        )
        self.assertTrue(review._checkout_matches_diff(self.root, diff))

    def test_a_deletion_only_diff_is_rejected_against_an_unrelated_directory(self):
        # Round-4 fix: collecting new_path made a deletion-only diff
        # (new_path is always None for a deletion) match unconditionally,
        # reinstating the "confident wrong context, no note" failure this
        # check exists to remove.
        make_tree(self.root, {"totally/unrelated/thing.py": "x = 1\n"})
        diff = (
            "diff --git a/gone.py b/gone.py\n"
            "deleted file mode 100644\n"
            "--- a/gone.py\n"
            "+++ /dev/null\n"
            "@@ -1,1 +0,0 @@\n"
            "-content\n"
        )
        self.assertFalse(review._checkout_matches_diff(self.root, diff))

    def test_a_deletion_only_diff_matches_a_checkout_containing_the_deleted_path(self):
        make_tree(self.root, {"gone.py": "content\n"})
        diff = (
            "diff --git a/gone.py b/gone.py\n"
            "deleted file mode 100644\n"
            "--- a/gone.py\n"
            "+++ /dev/null\n"
            "@@ -1,1 +0,0 @@\n"
            "-content\n"
        )
        self.assertTrue(review._checkout_matches_diff(self.root, diff))

    def test_a_diff_of_only_brand_new_files_always_matches(self):
        # No pre-existing path to check against: nothing here can prove or
        # disprove the checkout, so it is not rejected.
        make_tree(self.root, {"README.md": "hi\n"})
        diff = (
            "diff --git a/src/new_thing.py b/src/new_thing.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/src/new_thing.py\n"
            "@@ -0,0 +1,1 @@\n"
            "+brand new content\n"
        )
        self.assertTrue(review._checkout_matches_diff(self.root, diff))

    def test_an_empty_diff_matches(self):
        make_tree(self.root, {"README.md": "hi\n"})
        self.assertTrue(review._checkout_matches_diff(self.root, ""))


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

    def test_no_source_at_all_emits_nothing_rather_than_a_false_reason(self):
        # I2: offline with --diff-file and no --worktree (the tuning loop in
        # CLAUDE.md) there is no checkout and no client, so nothing was ever
        # opened. The section used to emit a stub per changed file claiming each
        # was "unreadable, binary, or over 524288 bytes" — a reason this code
        # knows to be false. Also reached in production when the tarball and the
        # per-file API both fail.
        out = review.pack_changed_files(
            None, None, "o/r", "sha",
            {"src/a.py": [(1, 5)], "src/b.py": [(1, 5)]}, self.cfg, self.acc())
        self.assertEqual(out, "")

    def test_a_genuinely_oversized_file_still_says_why_it_was_skipped(self):
        # The honest per-file message must survive: with a real checkout, "over
        # N bytes" is a true statement about a file that was really stat'd.
        make_tree(self.root, {"huge.py": "x\n" * 300_000, "ok.py": "fine\n"})
        out = review.pack_changed_files(
            self.root, None, "o/r", "sha",
            {"huge.py": [(1, 1)], "ok.py": [(1, 1)]}, self.cfg, self.acc())
        self.assertIn(f"over {review.MAX_SOURCE_BYTES} bytes", out)

    def test_a_failed_api_fetch_does_not_claim_the_file_is_binary(self):
        # The degraded per-file path: no checkout, and the API refuses. The file
        # may be perfectly ordinary — the fetch is what failed — so the note
        # must not assert anything about the file's contents.
        class RefusingGH:
            def file(self, repo, path, ref=None):
                raise RuntimeError("502")

        out = review.pack_changed_files(
            None, RefusingGH(), "o/r", "sha", {"src/a.py": [(1, 5)]}, self.cfg, self.acc())
        self.assertIn("src/a.py", out)
        self.assertNotIn("binary", out)
        self.assertIn("could not be fetched", out)

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

    def test_a_small_file_is_still_shown_when_a_bigger_one_sorts_ahead_and_cannot_fit(self):
        # Round-2 regression: round 1 stopped assembly entirely on the first
        # file that didn't fit, dropping every file behind it in priority
        # order too — even ones, like this small file, that would easily
        # have fit the room the big one could not use. aaa_huge.py sorts
        # first (tied hunk count, earlier alphabetically) and cannot fit even
        # fully windowed down; zzz_small.py must still get its own chance.
        huge_lines = "\n".join(f"line{i}" for i in range(1, 3001))  # 3000 lines
        make_tree(self.root, {
            "aaa_huge.py": huge_lines + "\n",
            "zzz_small.py": "alpha\nbeta\ngamma\n",
        })
        ranges = {"aaa_huge.py": [(1, 3000)], "zzz_small.py": [(1, 3)]}
        acc = self.acc(limit=5000)
        out = review.pack_changed_files(self.root, None, "o/r", "sha", ranges, self.cfg, acc)
        self.assertIn("### zzz_small.py\n```\n1: alpha\n2: beta\n3: gamma\n```\n", out)
        self.assertIn("### 1 further changed file(s) not shown (budget)\n- aaa_huge.py", out)
        self.assertLessEqual(len(out), acc.limits["changed_files"])
        self.assertNotIn("changed_files", acc.truncated)

    def test_the_section_uses_a_substantial_fraction_of_its_budget(self):
        # Round 1's stop-on-first-miss left roughly a third of a real
        # section's budget unused (67% utilisation on an actual PR) once one
        # oversized file stopped assembly and took every file behind it down
        # with it. The 85% floor here is set specifically high enough that
        # round 1's behaviour would have failed it.
        huge_lines = "\n".join(f"line{i}" for i in range(1, 3001))
        files = {"aaa_huge.py": huge_lines + "\n"}
        ranges = {"aaa_huge.py": [(1, 3000)]}
        body = "\n".join(f"line{i}" for i in range(1, 101)) + "\n"  # ~1 KB whole, numbered
        for i in range(5):
            name = f"m{i}.py"
            files[name] = body
            ranges[name] = [(1, 1)]
        make_tree(self.root, files)
        acc = self.acc(limit=6000)
        out = review.pack_changed_files(self.root, None, "o/r", "sha", ranges, self.cfg, acc)
        self.assertGreaterEqual(acc.used["changed_files"], 0.85 * acc.limits["changed_files"])
        self.assertLessEqual(len(out), acc.limits["changed_files"])
        self.assertNotIn("changed_files", acc.truncated)

    def test_a_file_over_its_cap_by_raw_size_is_windowed_in_not_dropped(self):
        # The specific round-1 regression: review.md in the real PR was
        # 21,343 raw chars against a 6,618 cap, but its ±60-padded window was
        # only 4,250 chars — comfortably fittable. A file must be judged on
        # what it actually renders to, never on raw size, so it is included
        # windowed rather than treated as unfittable.
        lines = "\n".join(f"line{i}" for i in range(1, 2001))  # 2000 lines, large raw
        make_tree(self.root, {"review.md": lines + "\n", "test.md": "alpha\nbeta\n"})
        ranges = {"review.md": [(1000, 1001)], "test.md": [(1, 2)]}
        acc = self.acc(limit=6000)
        out = review.pack_changed_files(self.root, None, "o/r", "sha", ranges, self.cfg, acc)
        self.assertIn("### review.md", out)
        self.assertIn("elided", out)
        self.assertIn("1000: line1000", out)
        self.assertIn("### test.md\n```\n1: alpha\n2: beta\n```\n", out)
        self.assertNotIn("not shown (budget)", out)
        self.assertLessEqual(len(out), acc.limits["changed_files"])
        self.assertNotIn("changed_files", acc.truncated)

    def test_utilisation_on_a_realistic_shape_stays_high_with_only_the_oversized_file_dropped(self):
        # Round 3 regression: mirrors the real PR's actual shape — several
        # medium files whose diffs touch only PART of a larger file (so they
        # window down usefully but easily fit whole given real headroom) plus
        # one file whose diff touches its ENTIRE body (so no window can ever
        # shrink it). Equal-division water-filling (round 2) let this one
        # unshrinkable outlier drag the shared "average" below what the
        # medium files actually needed, windowing them down needlessly even
        # though the budget to show them whole existed. The fix must exclude
        # a file that can never usefully shrink from that division.
        medium_specs = {
            "medium1.py": (200, (100, 105)),
            "medium2.py": (300, (140, 150)),
            "medium3.py": (150, (60, 65)),
        }
        files = {}
        ranges = {}
        for name, (n_lines, hunk) in medium_specs.items():
            files[name] = "\n".join(f"line{i}" for i in range(1, n_lines + 1)) + "\n"
            ranges[name] = [hunk]
        unfittable_lines = 3000
        files["unfittable.py"] = "\n".join(f"line{i}" for i in range(1, unfittable_lines + 1)) + "\n"
        ranges["unfittable.py"] = [(1, unfittable_lines)]  # touches the entire file
        make_tree(self.root, files)

        # Computed independently of pack_changed_files's own internals: each
        # whole file, numbered "N: lineN" one per line, wrapped in the same
        # "### name" + fence shape the section itself uses.
        def whole_size(name: str, n_lines: int) -> int:
            body = "\n".join(f"{i}: line{i}" for i in range(1, n_lines + 1))
            return len(f"### {name}\n```\n{body}\n```\n")

        medium_wholes = sum(whole_size(name, spec[0]) for name, spec in medium_specs.items())
        acc = self.acc(limit=medium_wholes + 400)  # just enough headroom for the mediums, not the outlier
        out = review.pack_changed_files(self.root, None, "o/r", "sha", ranges, self.cfg, acc)

        for name in medium_specs:
            self.assertIn(f"### {name}", out)
        self.assertIn("### 1 further changed file(s) not shown (budget)\n- unfittable.py", out)
        self.assertNotIn("elided", out)  # the mediums must be shown WHOLE, not windowed
        self.assertGreaterEqual(acc.used["changed_files"], 0.90 * acc.limits["changed_files"])
        self.assertLessEqual(len(out), acc.limits["changed_files"])
        self.assertNotIn("changed_files", acc.truncated)

    def test_files_that_collectively_fit_whole_are_never_windowed(self):
        # Direct guard for Finding 6: when the budget comfortably covers every
        # chosen file rendered whole, none of them should be windowed at all
        # — not even the largest of the bunch.
        files = {
            f"src/f{i}.py": "\n".join(f"line{i}_{j}" for j in range(1, 21)) + "\n"
            for i in range(5)
        }
        make_tree(self.root, files)
        ranges = {p: [(5, 8)] for p in files}
        acc = self.acc()  # generous default budget
        out = review.pack_changed_files(self.root, None, "o/r", "sha", ranges, self.cfg, acc)
        for p in files:
            self.assertIn(f"### {p}", out)
        self.assertNotIn("elided", out)
        self.assertNotIn("not shown", out)
        self.assertLessEqual(len(out), acc.limits["changed_files"])
        self.assertNotIn("changed_files", acc.truncated)

    def test_utilisation_stays_high_across_the_whole_file_count_range(self):
        # Round-4 regression, and the reason the round-1 sweep above was not
        # enough: it asserted only the ceiling (never overrun), so a build that
        # spent 15% of the budget passed it green. Utilisation has a floor too,
        # and the floor has to be checked at every file count, because the way
        # this collapsed was count-dependent — 97.8% on a 10-file PR, 15.2% on
        # a 19-file one, because single-shot allocation dropped every file to
        # its tightest window at once and never redistributed what that freed.
        #
        # Each file here is ~50 KB whole, so at EVERY count in the sweep —
        # including n=1 — the chosen files cannot all be shown whole and real
        # allocation has to happen. Two well-separated hunks per file, so the
        # padded window is a genuine middle rung between the tight window and
        # the whole file, and there is somewhere for the allocator to fail.
        line = "x" * 40
        body = "\n".join(f"line{i}{line}" for i in range(1, 901)) + "\n"
        for n in (1, 5, 10, 15, 19, 20, 25, 30):
            with self.subTest(n=n):
                tmp = tempfile.TemporaryDirectory()
                try:
                    root = pathlib.Path(tmp.name)
                    files = {f"src/f{i:02d}.py": body for i in range(n)}
                    make_tree(root, files)
                    ranges = {p: [(200, 205), (600, 605)] for p in files}
                    acc = self.acc()
                    out = review.pack_changed_files(
                        root, None, "o/r", "sha", ranges, self.cfg, acc)
                    limit = acc.limits["changed_files"]
                    self.assertLessEqual(len(out), limit)
                    self.assertNotIn("changed_files", acc.truncated)
                    self.assertGreaterEqual(
                        acc.used["changed_files"], 0.85 * limit,
                        f"n={n}: used {acc.used['changed_files']} of {limit} "
                        f"({100.0 * acc.used['changed_files'] / limit:.1f}%)")
                finally:
                    tmp.cleanup()

    def test_a_collectively_fitting_set_is_emitted_whole_with_every_line_present(self):
        # Stronger than "no elision marker appears": every line of every file
        # is asserted present under its own real line number, so a build that
        # dropped a file's tail, or renumbered it, cannot pass by rendering
        # something elision-free but incomplete.
        specs = {"a.py": 40, "b.py": 120, "c.py": 15, "d.py": 200}
        files = {name: "\n".join(f"line{i}" for i in range(1, n + 1)) + "\n"
                 for name, n in specs.items()}
        make_tree(self.root, files)
        ranges = {name: [(2, 3)] for name in specs}
        acc = self.acc()
        out = review.pack_changed_files(self.root, None, "o/r", "sha", ranges, self.cfg, acc)
        for name, n in specs.items():
            self.assertIn(f"### {name}", out)
            for i in (1, n // 2, n):
                self.assertIn(f"{i}: line{i}\n", out)
        self.assertNotIn("elided", out)
        self.assertNotIn("not shown", out)
        self.assertLessEqual(len(out), acc.limits["changed_files"])
        self.assertNotIn("changed_files", acc.truncated)

    def test_an_unfittable_top_priority_file_is_dropped_while_the_rest_are_shown(self):
        # Stronger than the round-2 test above, which put the unfittable file
        # first only by an alphabetical tiebreak. Here it has the MOST hunks,
        # so it is genuinely the top-priority file, and its diff touches its
        # entire body, so no window shrinks it below the whole budget. It has
        # to be dropped and named anyway — priority orders who gets served
        # first, it does not entitle one file to starve every other.
        huge = "\n".join(f"line{i}" for i in range(1, 4001)) + "\n"
        files = {"aaa_unfittable.py": huge}
        ranges = {"aaa_unfittable.py": [(1, 1000), (1001, 2000), (2001, 3000), (3001, 4000)]}
        for i in range(4):
            name = f"small{i}.py"
            files[name] = f"alpha{i}\nbeta{i}\ngamma{i}\n"
            ranges[name] = [(1, 3)]
        make_tree(self.root, files)
        acc = self.acc(limit=4000)
        out = review.pack_changed_files(self.root, None, "o/r", "sha", ranges, self.cfg, acc)
        self.assertIn("### 1 further changed file(s) not shown (budget)\n- aaa_unfittable.py", out)
        for i in range(4):
            self.assertIn(f"### small{i}.py\n```\n1: alpha{i}\n2: beta{i}\n3: gamma{i}\n```\n", out)
        self.assertLessEqual(len(out), acc.limits["changed_files"])
        self.assertNotIn("changed_files", acc.truncated)

    def test_the_busiest_file_outranks_a_crowd_of_trivial_ones_for_a_place(self):
        # Round-5 regression, and the whole point of ordering by hunk count.
        # Choosing a single evictee — even "the cheapest eviction that ends the
        # overflow" — can only ever remove ONE file, so when no individual
        # trivial file covers the overflow the one big file does, and the
        # most-changed file in the PR is dropped in favour of twenty files with
        # one trivial hunk each. Measured at the production budget before the
        # fix: A_core.py dropped, all 20 trivial files shown, 43.4% used.
        # Admission in priority order keeps A_core and turns away the tail.
        files = {"A_core.py": "\n".join(f"core{i}" + "y" * 44 for i in range(1, 901)) + "\n"}
        ranges = {"A_core.py": [(50, 130), (200, 280), (350, 430),
                                (500, 580), (650, 730), (800, 880)]}
        for i in range(20):                       # one hunk each: lowest priority
            name = f"z{i:02d}.py"
            files[name] = "\n".join(f"z{i:02d}line{j:02d}" for j in range(1, 61)) + "\n"
            ranges[name] = [(1, 60)]              # whole body touched: unshrinkable
        make_tree(self.root, files)
        acc = self.acc(limit=39840)               # the real production budget
        out = review.pack_changed_files(self.root, None, "o/r", "sha", ranges, self.cfg, acc)

        self.assertIn("### A_core.py\n", out)                 # the busiest file survives
        self.assertNotIn("- A_core.py", out)                  # and is not in any drop list
        dropped = [ln[2:] for ln in out.splitlines() if ln.startswith("- ")]
        self.assertTrue(dropped, "the fixture must not fit whole, or it proves nothing")
        # Whatever was turned away is a tail of the priority order: the trivial
        # files, lowest-ranked first, never something from the front.
        self.assertEqual(dropped, sorted(f"z{i:02d}.py" for i in range(20))[-len(dropped):])
        self.assertGreaterEqual(acc.used["changed_files"], 0.85 * acc.limits["changed_files"])
        self.assertLessEqual(len(out), acc.limits["changed_files"])
        self.assertNotIn("changed_files", acc.truncated)

    def test_an_unshrinkable_file_yields_its_place_to_the_smaller_files_behind_it(self):
        # The counter-case the rule above must not regress, modelled on the
        # real PR: seven shrinkable code files, then review.md whose diff
        # touches all of its own body (so no window shrinks it and it cannot be
        # admitted at its turn), then test.md sorting behind it. Strict
        # reverse-priority eviction takes test.md first and ends at eight
        # files; the unshrinkable one has to be the one that goes.
        files, ranges = {}, {}
        for i in range(7):
            name = f"src/code{i}.ts"
            files[name] = "\n".join(f"code{i} line {j} " + "z" * 30 for j in range(1, 121)) + "\n"
            ranges[name] = [(10, 40), (70, 100)]  # two hunks: shrinkable, higher priority
        files["docs/review.md"] = "\n".join(f"review line {j} " + "w" * 55 for j in range(1, 301)) + "\n"
        ranges["docs/review.md"] = [(1, 300)]     # the entire body
        files["docs/test.md"] = "\n".join(f"test line {j}" for j in range(1, 33)) + "\n"
        ranges["docs/test.md"] = [(1, 32)]
        make_tree(self.root, files)
        acc = self.acc(limit=39840)
        out = review.pack_changed_files(self.root, None, "o/r", "sha", ranges, self.cfg, acc)

        self.assertIn("### 1 further changed file(s) not shown (budget)\n- docs/review.md", out)
        self.assertIn("### docs/test.md\n", out)              # the small file behind it survives
        self.assertIn("1: test line 1\n", out)
        for i in range(7):
            self.assertIn(f"### src/code{i}.ts\n", out)
        self.assertGreaterEqual(acc.used["changed_files"], 0.85 * acc.limits["changed_files"])
        self.assertLessEqual(len(out), acc.limits["changed_files"])
        self.assertNotIn("changed_files", acc.truncated)

    def test_utilisation_holds_on_a_non_uniform_mix_of_sizes_and_hunk_counts(self):
        # The sweep above uses identical files, which is exactly why the
        # eviction defect passed it green: with uniform bodies the survivors
        # inflate to whole and utilisation stays near 100% no matter WHICH
        # files survive. Here sizes span 25 to 3000 lines and hunk counts 1 to
        # 6, some diffs cover a file's whole body and some a sliver of it, so
        # priority order, shrinkability and size all disagree with each other.
        sizes = [3000, 25, 480, 120, 60, 1500, 200, 45, 900, 75, 340, 30]
        files, ranges = {}, {}
        for i, n in enumerate(sizes):
            name = f"pkg{i % 3}/mod{i:02d}.py"
            files[name] = "\n".join(f"m{i:02d} line {j} " + "q" * (i * 3 % 40)
                                    for j in range(1, n + 1)) + "\n"
            if i % 4 == 3:
                ranges[name] = [(1, n)]                     # whole body: unshrinkable
            else:
                hunks = 1 + i % 6
                step = max(2, n // (hunks + 1))
                ranges[name] = [(k * step, min(n, k * step + 4)) for k in range(1, hunks + 1)]
        make_tree(self.root, files)
        acc = self.acc(limit=39840)
        out = review.pack_changed_files(self.root, None, "o/r", "sha", ranges, self.cfg, acc)
        limit = acc.limits["changed_files"]
        self.assertLessEqual(len(out), limit)
        self.assertNotIn("changed_files", acc.truncated)
        self.assertGreaterEqual(
            acc.used["changed_files"], 0.85 * limit,
            f"used {acc.used['changed_files']} of {limit} "
            f"({100.0 * acc.used['changed_files'] / limit:.1f}%)")

    def test_the_section_keeps_the_highest_priority_files_that_fit(self):
        # The other half of Finding 7, and the general form of it. A file is
        # turned away by comparing the section against the trailer AS IT STANDS
        # AT THE TIME, and every later refusal lengthens that trailer — so a
        # file can be refused for room that is handed back afterwards, and the
        # give-back takes the largest file it can, which walks DOWN from the top
        # of the priority order. Before the fix this fixture at a 3000-char
        # budget showed the busiest file plus the three LOWEST-priority filler
        # files, dropping ranks 1 through 16 outright.
        #
        # Asserted as the optimality condition rather than a hand-read expected
        # list: for every file named as budget-dropped, keeping it instead —
        # alongside every higher-priority file that was kept, and sacrificing
        # every lower-priority one — must genuinely not fit. That is exactly
        # what admitting in priority order guarantees, and it is violated by any
        # rule that drops a high-priority file a cheaper sacrifice would have
        # saved.
        files, ranges = {}, {}

        def add(name, n_lines, width):
            files[name] = "\n".join(f"{name[-9:]} line {j} " + "v" * width
                                    for j in range(1, n_lines + 1)) + "\n"
            ranges[name] = [(1, n_lines)]     # whole body: unshrinkable, so the
            #                                   floor is the only rendering
        add("pkg/r00_tiny_but_busiest.py", 6, 20)          # rank 0, cheap
        add("pkg/r01_bulky_unshrinkable.py", 40, 45)       # rank 1, the give-back's target
        add("pkg/r02_medium_unshrinkable.py", 16, 42)      # rank 2, refused early
        for i in range(18):
            add(f"pkg/r{i + 3:02d}_filler_padding_name.py", 12, 18)
        make_tree(self.root, files)

        chosen = sorted(ranges, key=lambda p: (-len(ranges[p]), p))[:25]
        floors = {r: review._file_tiers(r, files[r], ranges[r], "skipped")[0][1]
                  for r in chosen}
        for limit in (2500, 3000, 3500, 5000, 8000):
            with self.subTest(limit=limit):
                acc = self.acc(limit=limit)
                out = review.pack_changed_files(
                    self.root, None, "o/r", "sha", ranges, self.cfg, acc)
                self.assertLessEqual(len(out), limit)
                self.assertNotIn("changed_files", acc.truncated)
                header = out.split("### ")[0]
                shown = [ln[4:] for ln in out.splitlines()
                         if ln.startswith("### ") and ln.endswith(".py")]
                self.assertTrue(shown, "nothing shown; the fixture proves nothing")
                for d in [r for r in chosen if r not in shown]:
                    rank = chosen.index(d)
                    keep = [r for r in chosen
                            if r in shown and chosen.index(r) < rank] + [d]
                    keep.sort(key=chosen.index)
                    drop = [r for r in chosen if r not in keep]
                    groups = review._trailer_groups([], [], drop, with_names=True)
                    sizes = [len(floors[r]) for r in keep] + [len(g) for g in groups]
                    counterfactual = len(header) + sum(sizes) + max(0, len(sizes) - 1)
                    self.assertGreater(
                        counterfactual, limit,
                        f"limit={limit}: {d} (rank {rank}) was dropped, but keeping "
                        f"it and sacrificing every lower-priority file fits in "
                        f"{counterfactual} of {limit}")

    def test_a_tiny_budget_with_a_long_dropped_file_list_does_not_truncate(self):
        # Folded-in Minor: the trailer-shrink loop used to exit unconditionally
        # once shown_parts was empty, even if header + trailer alone still
        # exceeded budget — which could let Accounting truncate the section
        # outright, breaking the no-overrun contract at the very budgets where
        # it matters most.
        files = {f"src/f{i}.py": f"body{i}\n" for i in range(30)}
        make_tree(self.root, files)
        ranges = {p: [(1, 1)] for p in files}
        cfg = dict(self.cfg, max_context_files=0)  # everything lands in one long drop list
        for limit in (0, 1, 50, 300, 1000):
            with self.subTest(limit=limit):
                acc = self.acc(limit=limit)
                out = review.pack_changed_files(self.root, None, "o/r", "sha", ranges, cfg, acc)
                self.assertLessEqual(len(out), acc.limits["changed_files"])
                self.assertNotIn("changed_files", acc.truncated)


SYMBOL_DIFF = """\
diff --git a/src/api.py b/src/api.py
--- a/src/api.py
+++ b/src/api.py
@@ -1,4 +1,8 @@
-def fetch_user(uid):
+def fetch_user(uid, *, strict=False):
+class UserCache:
+    pass
+def go(x):
+export const parseToken = (raw) => raw
 unchanged
"""


class TestChangedSymbols(unittest.TestCase):
    def test_a_changed_function_is_extracted(self):
        self.assertIn("fetch_user", review.changed_symbols(SYMBOL_DIFF))

    def test_a_new_class_is_extracted(self):
        self.assertIn("UserCache", review.changed_symbols(SYMBOL_DIFF))

    def test_an_exported_const_is_extracted(self):
        self.assertIn("parseToken", review.changed_symbols(SYMBOL_DIFF))

    def test_short_names_are_dropped(self):
        self.assertNotIn("go", review.changed_symbols(SYMBOL_DIFF))

    def test_stoplisted_names_are_dropped(self):
        diff = "+++ b/a.py\n@@ -1,1 +1,1 @@\n+def value(self):\n"
        self.assertNotIn("value", review.changed_symbols(diff))

    def test_unchanged_lines_contribute_nothing(self):
        self.assertNotIn("unchanged", review.changed_symbols(SYMBOL_DIFF))

    def test_results_are_deduplicated_and_ordered(self):
        diff = "+++ b/a.py\n@@ -1,1 +1,2 @@\n+def alpha_one():\n+def alpha_one():\n"
        self.assertEqual(review.changed_symbols(diff), ["alpha_one"])

    def test_the_full_symbol_list_is_exactly_the_definition_shaped_names_in_order(self):
        # Weak-assertion guard: every prior test in this class uses assertIn/
        # assertNotIn on one name at a time, which would miss a spurious EXTRA
        # symbol slipping into the result. Pin down the whole list.
        self.assertEqual(
            review.changed_symbols(SYMBOL_DIFF),
            ["fetch_user", "UserCache", "parseToken"],
        )

    def test_more_than_max_symbols_changed_is_capped_at_max_symbols(self):
        # A tiny fixture can never exercise the 20-symbol cap; this changes 25
        # distinct, non-stoplisted, adequately-long names so the cap actually
        # has to bite, and pins the exact surviving prefix rather than just
        # asserting a count.
        names = [f"sym_{i:03d}" for i in range(25)]
        diff = "+++ b/a.py\n@@ -1,1 +1,25 @@\n" + "".join(f"+def {n}():\n" for n in names)
        out = review.changed_symbols(diff)
        self.assertEqual(len(out), review.MAX_SYMBOLS)
        self.assertEqual(out, names[: review.MAX_SYMBOLS])

    def test_prose_in_a_markdown_hunk_contributes_no_symbol_but_a_code_hunk_does(self):
        # Finding 4 (round 1 review): DEF_RE's bare "type <name>" alternative
        # fires on ordinary English sentences with no idea what file it is
        # reading. Attributing each hunk to its own path via _hunks() and
        # skipping non-code files fixes it — this diff's markdown hunk reads
        # "a type explaining the split", which would previously have yielded
        # "explaining"; the code hunk right after it must still work.
        diff = (
            "diff --git a/docs/notes.md b/docs/notes.md\n"
            "--- a/docs/notes.md\n"
            "+++ b/docs/notes.md\n"
            "@@ -1,1 +1,1 @@\n"
            "+a type explaining the split\n"
            "diff --git a/src/real.py b/src/real.py\n"
            "--- a/src/real.py\n"
            "+++ b/src/real.py\n"
            "@@ -1,1 +1,1 @@\n"
            "+def real_symbol():\n"
        )
        self.assertEqual(review.changed_symbols(diff), ["real_symbol"])


class TestGrepRepo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.cfg = dict(review.DEFAULTS)
        self.addCleanup(self.tmp.cleanup)

    def test_a_hit_carries_path_line_and_text(self):
        make_tree(self.root, {"caller.py": "import x\nfetch_user(7)\n"})
        hits = review.grep_repo(self.root, ["fetch_user"], self.cfg, exclude=set(), max_hits=40)
        self.assertEqual(hits["fetch_user"][0][0], "caller.py")
        self.assertEqual(hits["fetch_user"][0][1], 2)
        self.assertIn("fetch_user(7)", hits["fetch_user"][0][2])

    def test_the_changed_files_themselves_are_excluded(self):
        make_tree(self.root, {"src/api.py": "fetch_user\n"})
        hits = review.grep_repo(
            self.root, ["fetch_user"], self.cfg, exclude={"src/api.py"}, max_hits=40)
        self.assertEqual(hits.get("fetch_user", []), [])

    def test_a_symbol_over_the_hit_ceiling_is_dropped_entirely(self):
        # 50 hits is above SYMBOL_HIT_CEILING (40), so the symbol is dropped
        # rather than sampled down to max_hits.
        make_tree(self.root, {f"f{i}.py": "common_name\n" for i in range(50)})
        hits = review.grep_repo(self.root, ["common_name"], self.cfg, exclude=set(), max_hits=3)
        self.assertNotIn("common_name", hits)

    def test_a_symbol_under_the_ceiling_is_capped_at_max_hits(self):
        make_tree(self.root, {f"f{i}.py": "rare_name\n" for i in range(5)})
        hits = review.grep_repo(self.root, ["rare_name"], self.cfg, exclude=set(), max_hits=3)
        self.assertEqual(len(hits["rare_name"]), 3)

    def test_ignored_paths_are_not_searched(self):
        make_tree(self.root, {"Cargo.lock": "fetch_user\n"})
        hits = review.grep_repo(self.root, ["fetch_user"], self.cfg, exclude=set(), max_hits=40)
        self.assertEqual(hits.get("fetch_user", []), [])

    def test_binary_files_are_not_searched(self):
        make_tree(self.root, {"blob.bin": "fetch_user\x00\x01"})
        hits = review.grep_repo(self.root, ["fetch_user"], self.cfg, exclude=set(), max_hits=40)
        self.assertEqual(hits.get("fetch_user", []), [])

    def test_a_dot_git_directory_is_skipped(self):
        make_tree(self.root, {".git/objects/thing": "fetch_user\n"})
        hits = review.grep_repo(self.root, ["fetch_user"], self.cfg, exclude=set(), max_hits=40)
        self.assertEqual(hits.get("fetch_user", []), [])

    def test_a_needle_right_at_the_ceiling_is_kept_in_full(self):
        # Boundary check for "<= SYMBOL_HIT_CEILING": exactly 40 hits (the
        # ceiling itself) must survive, capped at max_hits, not be dropped
        # the way 41 would be. Distinguishes <= from < in the implementation.
        make_tree(self.root, {f"f{i}.py": "boundary_name\n" for i in range(40)})
        hits = review.grep_repo(
            self.root, ["boundary_name"], self.cfg, exclude=set(), max_hits=40)
        self.assertEqual(len(hits["boundary_name"]), 40)

    def test_multiple_needles_are_tracked_independently(self):
        # A set-equality guard: with several needles in play, each symbol's
        # hit dict must contain exactly its own hits, no cross-contamination
        # and no spurious extras from another needle's matches.
        make_tree(self.root, {
            "a.py": "alpha_thing()\n",
            "b.py": "beta_thing()\nalpha_thing()\n",
            "c.py": "gamma_thing()\n",
        })
        hits = review.grep_repo(
            self.root, ["alpha_thing", "beta_thing", "gamma_thing"], self.cfg,
            exclude=set(), max_hits=40)
        self.assertEqual(sorted(hits), ["alpha_thing", "beta_thing", "gamma_thing"])
        self.assertEqual(
            sorted((rel, ln) for rel, ln, _ in hits["alpha_thing"]),
            [("a.py", 1), ("b.py", 2)],
        )
        self.assertEqual(len(hits["beta_thing"]), 1)
        self.assertEqual(len(hits["gamma_thing"]), 1)

    def test_a_markdown_mention_is_not_a_hit_but_a_code_reference_is(self):
        # Finding 3 (round 1 review): an unrestricted walk cannot distinguish
        # a doc file quoting an identifier from a genuine call site. Exact hit
        # set, not assertIn: a regression here would silently ADD a doc hit
        # alongside the real one rather than replace it.
        make_tree(self.root, {
            "docs/notes.md": "See fetch_user for details.\nfetch_user again here.\n",
            "src/caller.py": "fetch_user(1)\n",
        })
        hits = review.grep_repo(self.root, ["fetch_user"], self.cfg, exclude=set(), max_hits=40)
        self.assertEqual(
            [(rel, ln) for rel, ln, _ in hits["fetch_user"]],
            [("src/caller.py", 1)],
        )

    def test_non_code_suffixes_are_never_walked(self):
        # Direct guard on walk_source's own contract, independent of any
        # particular needle: nothing outside CODE_SUFFIXES is ever yielded,
        # so it cannot appear in ANY needle's hits, present or future.
        make_tree(self.root, {
            "README.md": "shared_token\n",
            "data.json": "shared_token\n",
            "notes.txt": "shared_token\n",
            "src/real.py": "shared_token\n",
        })
        rels = {rel for rel, _text in review.walk_source(self.root, self.cfg)}
        self.assertEqual(rels, {"src/real.py"})


class TestModuleStem(unittest.TestCase):
    def test_a_test_suffixed_typescript_file_yields_the_bare_module_name(self):
        # Finding 2 (round 1 review): stripping only the final extension left
        # ".test" glued to the stem, so the needle could only ever match the
        # test file's own name, never a real `import HandicapHero`.
        self.assertEqual(
            review._module_stem("apps/web/src/dashboard/HandicapHero.test.tsx"),
            "HandicapHero",
        )

    def test_a_spec_suffixed_javascript_file_yields_the_bare_module_name(self):
        self.assertEqual(review._module_stem("src/Sparkline.spec.js"), "Sparkline")

    def test_an_ordinary_module_file_is_unaffected(self):
        self.assertEqual(review._module_stem("src/trends/handicapModel.ts"), "handicapModel")

    def test_a_bare_filename_with_no_directory_still_works(self):
        self.assertEqual(review._module_stem("api.py"), "api")


class TestPackCallSites(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.cfg = dict(review.DEFAULTS)
        self.addCleanup(self.tmp.cleanup)

    def acc(self, call_sites=15000):
        return review.Accounting({"changed_files": 1, "call_sites": call_sites, "conventions": 1,
                                  "requirements": 1, "tree": 1})

    def test_a_caller_outside_the_diff_is_reported(self):
        make_tree(self.root, {
            "src/api.py": "def fetch_user(uid):\n    pass\n",
            "web/view.py": "from src.api import fetch_user\nfetch_user(1)\n",
        })
        out = review.pack_call_sites(
            self.root, SYMBOL_DIFF, {"src/api.py": [(1, 8)]}, self.cfg, self.acc())
        self.assertIn("web/view.py", out)

    def test_importers_of_a_changed_module_are_reported(self):
        # Note the module stem must clear MIN_SYMBOL_LEN: "service" does, "api"
        # would not, so a three-letter module contributes no importer needle.
        make_tree(self.root, {
            "src/service.py": "x = 1\n",
            "web/view.py": "from src.service import thing\n",
        })
        out = review.pack_call_sites(
            self.root, "--- a/src/service.py\n+++ b/src/service.py\n@@ -1,1 +1,1 @@\n+x = 2\n",
            {"src/service.py": [(1, 1)]}, self.cfg, self.acc())
        self.assertIn("web/view.py", out)

    def test_no_checkout_yields_an_empty_section(self):
        self.assertEqual(
            review.pack_call_sites(None, SYMBOL_DIFF, {}, self.cfg, self.acc()), "")

    def test_no_hits_yields_an_empty_section(self):
        make_tree(self.root, {"src/api.py": "def fetch_user(uid):\n    pass\n"})
        out = review.pack_call_sites(
            self.root, SYMBOL_DIFF, {"src/api.py": [(1, 8)]}, self.cfg, self.acc())
        self.assertNotIn("### ", out)

    def test_more_symbols_than_the_cap_lose_the_module_importer_needle(self):
        # Exercises the 20-symbol cap concretely, at the pack_call_sites level:
        # 20 distinct changed symbols already fill `needles` to MAX_SYMBOLS, so
        # slicing to [:MAX_SYMBOLS] squeezes out the module-stem needle even
        # though it would otherwise find a real importer. Assert the exact set
        # of `### \`name\`` headers produced, not merely that one is present.
        names = [f"sym_{i:03d}" for i in range(review.MAX_SYMBOLS)]
        diff = "+++ b/src/service.py\n@@ -1,1 +1,20 @@\n" + "".join(
            f"+def {n}():\n" for n in names)
        files = {"src/service.py": "\n".join(f"def {n}(): pass" for n in names) + "\n"}
        # Every changed symbol has exactly one caller outside the diff...
        for i, n in enumerate(names):
            files[f"callers/c{i}.py"] = f"{n}()\n"
        # ...and the module "service" also has an importer, which must NOT
        # show up because the needle list is already full of symbols.
        files["web/view.py"] = "from src.service import thing\n"
        make_tree(self.root, files)
        out = review.pack_call_sites(
            self.root, diff, {"src/service.py": [(1, 20)]}, self.cfg, self.acc())

        found = set(re.findall(r"### `([^`]+)`", out))
        self.assertEqual(found, set(names))
        self.assertNotIn("web/view.py", out)

    def test_the_section_is_truncated_in_band_when_it_exceeds_its_budget(self):
        # A large, shaped fixture: enough distinct symbols, each with enough
        # hits, that the rendered section is far bigger than a deliberately
        # tiny call_sites budget — so the branch that actually exercises
        # Accounting's truncation runs, rather than a fixture too small to
        # ever reach it.
        names = [f"big_symbol_{i:03d}" for i in range(review.MAX_SYMBOLS)]
        diff = "+++ b/src/big.py\n@@ -1,1 +1,20 @@\n" + "".join(
            f"+def {n}():\n" for n in names)
        files = {}
        for i, n in enumerate(names):
            files[f"callers/c{i}.py"] = "\n".join(f"{n}(argument_number_{j})" for j in range(5)) + "\n"
        make_tree(self.root, files)
        acc = self.acc(call_sites=200)
        out = review.pack_call_sites(
            self.root, diff, {"src/big.py": [(1, 20)]}, self.cfg, acc)
        self.assertLessEqual(len(out), 200)
        self.assertIn("call_sites", acc.truncated)
        self.assertIn("…", out)
        # A marker is not enough: this cut lands inside the per-needle fence,
        # and an open fence quotes every later section, the lens brief and
        # LENS_TAIL along with it. See TestFenceBalanceUnderTruncation.
        self.assertIsNone(unclosed_fence(out))


class TestPackCallSitesDeterminism(unittest.TestCase):
    """Finding 1 (round 1 review): iterating `set(ranges)` to build importer
    needles made which module stems survive the 20-slot cap depend on
    CPython's per-process string-hash randomisation — same diff, same
    checkout, different section. Fixed by iterating `ranges` (an
    insertion-ordered dict) directly.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _big_fixture(self, prefix: str, n: int = 30):
        """`n` (> MAX_SYMBOLS) changed files, each importer-worthy and each
        imported from its own caller file, plus the `ranges`/files dicts
        needed to drive `pack_call_sites` from modules alone (diff="").
        """
        names = [f"{prefix}_{i:03d}" for i in range(n)]
        files, ranges = {}, {}
        for i, name in enumerate(names):
            rel = f"src/{name}.py"
            files[rel] = f"x = {i}\n"
            ranges[rel] = [(1, 1)]
            files[f"callers/c{i}.py"] = f"import {name}\n"
        return names, files, ranges

    def test_the_surviving_needles_are_exactly_the_first_ranges_entries_in_order(self):
        # A fixture too small to force a choice would pass even with the old
        # set-based code most of the time; 30 candidates against a 20-slot
        # cap forces the ordering to actually decide who is dropped, and the
        # dropped set is pinned exactly rather than merely "some are missing".
        names, files, ranges = self._big_fixture("stem")
        make_tree(self.root, files)
        cfg = dict(review.DEFAULTS)
        acc = review.Accounting({"changed_files": 1, "call_sites": 50000, "conventions": 1,
                                  "requirements": 1, "tree": 1})
        out = review.pack_call_sites(self.root, "", ranges, cfg, acc)
        found = set(re.findall(r"### `([^`]+)`", out))
        self.assertEqual(found, set(names[: review.MAX_SYMBOLS]))

    def test_the_section_is_byte_identical_across_python_hash_seeds(self):
        # The direct regression guard for Finding 1: run the same call in
        # fresh subprocesses under different PYTHONHASHSEED values (which
        # only affects str hashing, and therefore only a *set's* iteration
        # order — dict insertion order is unaffected by it either way) and
        # assert the produced section is byte-for-byte identical every time.
        # This would have failed under the old `for rel in set(ranges):` code.
        names, files, ranges = self._big_fixture("seed")
        make_tree(self.root, files)

        review_dir = str(pathlib.Path(review.__file__).resolve().parent)
        script = (
            "import sys, pathlib\n"
            f"sys.path.insert(0, {review_dir!r})\n"
            "import review\n"
            f"ranges = {ranges!r}\n"
            "cfg = dict(review.DEFAULTS)\n"
            "acc = review.Accounting({'changed_files': 1, 'call_sites': 50000,\n"
            "                         'conventions': 1, 'requirements': 1, 'tree': 1})\n"
            f"out = review.pack_call_sites(pathlib.Path({str(self.root)!r}), '', ranges, cfg, acc)\n"
            "sys.stdout.write(out)\n"
        )
        outputs = []
        for seed in ("0", "1", "42"):
            proc = subprocess.run(
                [sys.executable, "-c", script],
                env={**os.environ, "PYTHONHASHSEED": seed},
                capture_output=True, text=True, check=True,
            )
            outputs.append(proc.stdout)
        self.assertTrue(outputs[0], "the fixture produced nothing; it proves nothing")
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0], outputs[2])


class TestPackConventions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def acc(self, conventions=12000):
        return review.Accounting({"changed_files": 1, "call_sites": 1, "conventions": conventions,
                                  "requirements": 1, "tree": 6000})

    def _headers(self, out):
        return re.findall(r"(?m)^### (.+)$", out)

    def _fence_line_after(self, out, heading):
        """The exact line right after `heading` (e.g. "### CLAUDE.md\n") — the
        opening fence a document was wrapped in."""
        idx = out.index(heading) + len(heading)
        return out[idx: out.index("\n", idx)]

    def test_a_root_claude_md_is_included(self):
        make_tree(self.root, {"CLAUDE.md": "Always use tabs.\n"})
        out = review.pack_conventions(self.root, {"src/a.py": [(1, 1)]}, self.acc())
        self.assertEqual(self._headers(out), ["CLAUDE.md"])
        self.assertIn("Always use tabs.", out)

    def test_a_nearest_ancestor_file_is_included(self):
        make_tree(self.root, {"web/AGENTS.md": "Web rules.\n"})
        out = review.pack_conventions(self.root, {"web/app/x.py": [(1, 1)]}, self.acc())
        self.assertEqual(self._headers(out), ["web/AGENTS.md"])
        self.assertIn("Web rules.", out)

    def test_readme_is_used_only_when_nothing_else_exists(self):
        make_tree(self.root, {"README.md": "Readme text.\n"})
        out = review.pack_conventions(self.root, {"src/a.py": [(1, 1)]}, self.acc())
        self.assertEqual(self._headers(out), ["README.md"])
        self.assertIn("Readme text.", out)

    def test_readme_is_omitted_when_a_conventions_file_exists(self):
        make_tree(self.root, {"README.md": "Readme text.\n", "CONTRIBUTING.md": "Contribute.\n"})
        out = review.pack_conventions(self.root, {"src/a.py": [(1, 1)]}, self.acc())
        self.assertEqual(self._headers(out), ["CONTRIBUTING.md"])
        self.assertNotIn("Readme text.", out)

    def test_multi_level_ancestors_are_collected_deepest_first_root_last(self):
        # Real depth: a root file, a mid-level file, and a file right next to
        # the change, all three distinct so order is unambiguous. Ordered by
        # descending directory depth: web/app/CONTRIBUTING.md (depth 2) before
        # web/AGENTS.md (depth 1) before the root CLAUDE.md (depth 0) — nearest
        # to the change first, root last, so truncation sacrifices the root
        # file rather than the nearest one.
        make_tree(self.root, {
            "CLAUDE.md": "Root CLAUDE conventions.\n",
            "web/AGENTS.md": "Web AGENTS conventions.\n",
            "web/app/CONTRIBUTING.md": "App CONTRIBUTING conventions.\n",
        })
        out = review.pack_conventions(self.root, {"web/app/deep/mod.py": [(1, 1)]}, self.acc())
        self.assertEqual(
            self._headers(out),
            ["web/app/CONTRIBUTING.md", "web/AGENTS.md", "CLAUDE.md"],
        )
        self.assertIn("Root CLAUDE conventions.", out)
        self.assertIn("App CONTRIBUTING conventions.", out)
        self.assertIn("Web AGENTS conventions.", out)

    def test_two_touched_branches_are_ordered_by_distance_not_absolute_depth(self):
        # Round-2 fix: absolute directory depth is the wrong proxy across
        # branches. "api/AGENTS.md" sits *in* its changed directory
        # (api/handler.py -> distance 0), while "web/app/CONTRIBUTING.md" is
        # one level above its changed directory (web/app/deep/mod.py's own
        # dir is web/app/deep -> distance 1) despite living at a deeper
        # absolute path. Distance must rank the genuinely adjacent file
        # first even though it is shallower in absolute terms — this test
        # replaces a round-1 test that asserted the old (wrong) absolute-depth
        # order, which put web/app/CONTRIBUTING.md first.
        make_tree(self.root, {
            "CLAUDE.md": "Root rules.\n",
            "api/AGENTS.md": "Api rules.\n",
            "web/app/CONTRIBUTING.md": "Web app rules.\n",
        })
        ranges = {"api/handler.py": [(1, 1)], "web/app/deep/mod.py": [(1, 1)]}
        out = review.pack_conventions(self.root, ranges, self.acc())
        self.assertEqual(
            self._headers(out),
            ["api/AGENTS.md", "web/app/CONTRIBUTING.md", "CLAUDE.md"],
        )

    def test_a_shallower_but_adjacent_file_outranks_a_deeper_but_distant_one(self):
        # The exact reproduction from the round-2 finding: a/CLAUDE.md sits
        # directly in the changed directory "a" (distance 0), while
        # x/y/AGENTS.md is two levels above the changed directory "x/y/z"
        # (distance 2) despite x/y being absolutely deeper than "a". The
        # adjacent file must survive a tight budget; the merely-deeper one
        # must not. Swept across three budgets so this does not hinge on one
        # lucky threshold.
        make_tree(self.root, {
            "a/CLAUDE.md": "adjacentadjacent" * 500 + "\n",
            "x/y/AGENTS.md": "distantdistant" * 500 + "\n",
        })
        ranges = {"a/file.py": [(1, 1)], "x/y/z/w.py": [(1, 1)]}
        out_full = review.pack_conventions(self.root, ranges, self.acc(conventions=1_000_000))
        self.assertEqual(self._headers(out_full), ["a/CLAUDE.md", "x/y/AGENTS.md"])
        for budget in (5200, 5000, 4800):
            with self.subTest(budget=budget):
                out = review.pack_conventions(self.root, ranges, self.acc(conventions=budget))
                self.assertIn("truncated", out)
                self.assertIn("adjacentadjacent", out)
                self.assertNotIn("distantdistant", out)

    def test_equal_distance_ties_are_deterministic_across_repeated_calls(self):
        # Two branches whose convention files each sit directly in their own
        # changed directory (distance 0 for both) force a real tie, broken
        # only by the (-depth, path) tail of the sort key. Run several times
        # in-process, and again across hash seeds in a subprocess (the same
        # failure mode as the previous determinism bugs on this plan), and
        # assert byte-identical output every time.
        make_tree(self.root, {
            "api/AGENTS.md": "Api rules.\n",
            "web/CONTRIBUTING.md": "Web rules.\n",
        })
        ranges = {"api/handler.py": [(1, 1)], "web/app.py": [(1, 1)]}
        first = review.pack_conventions(self.root, ranges, self.acc())
        # Both are distance 0 and equal depth, so the path tie-break decides:
        # "api" sorts before "web".
        self.assertEqual(self._headers(first), ["api/AGENTS.md", "web/CONTRIBUTING.md"])
        for _ in range(5):
            self.assertEqual(review.pack_conventions(self.root, ranges, self.acc()), first)

        review_dir = str(pathlib.Path(review.__file__).resolve().parent)
        script = (
            "import sys, pathlib\n"
            f"sys.path.insert(0, {review_dir!r})\n"
            "import review\n"
            f"ranges = {ranges!r}\n"
            "acc = review.Accounting({'changed_files': 1, 'call_sites': 1,\n"
            "                         'conventions': 12000, 'requirements': 1, 'tree': 6000})\n"
            f"out = review.pack_conventions(pathlib.Path({str(self.root)!r}), ranges, acc)\n"
            "sys.stdout.write(out)\n"
        )
        outputs = []
        for seed in ("0", "1", "42"):
            proc = subprocess.run(
                [sys.executable, "-c", script],
                env={**os.environ, "PYTHONHASHSEED": seed},
                capture_output=True, text=True, check=True,
            )
            outputs.append(proc.stdout)
        self.assertTrue(outputs[0], "the fixture produced nothing; it proves nothing")
        self.assertEqual(outputs[0], first)
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0], outputs[2])

    def test_a_shared_ancestor_file_is_not_duplicated_across_changed_files(self):
        make_tree(self.root, {"src/CLAUDE.md": "Src rules.\n"})
        out = review.pack_conventions(
            self.root, {"src/a.py": [(1, 1)], "src/sub/b.py": [(1, 1)]}, self.acc()
        )
        self.assertEqual(self._headers(out).count("src/CLAUDE.md"), 1)

    def test_truncation_keeps_the_nearest_file_and_drops_the_farther_one(self):
        # Two real convention files, each large enough that a budget between
        # "nearest alone" and "both" forces a real choice — a fixture where
        # every file is a few bytes could pass this even with the priority
        # backwards.
        make_tree(self.root, {
            "web/AGENTS.md": "farfarfar" * 600 + "\n",
            "web/app/CONTRIBUTING.md": "nearnearnear" * 600 + "\n",
        })
        ranges = {"web/app/x.py": [(1, 1)]}
        full = review.pack_conventions(self.root, ranges, self.acc(conventions=1_000_000))
        # Nearest (CONTRIBUTING) is emitted first; this is where the farther
        # file's (AGENTS) content begins in the untruncated text.
        boundary = full.index("farfarfar")
        out = review.pack_conventions(self.root, ranges, self.acc(conventions=boundary))
        self.assertIn("truncated", out)
        self.assertIn("nearnearnear" * 590, out)
        self.assertNotIn("farfarfar", out)

    def test_a_root_file_is_the_one_sacrificed_when_a_nearer_file_also_exists(self):
        # The exact combination the inverted-order bug missed: a root
        # convention file *and* a nearer one, budget swept across several
        # tight values so the assertion does not hinge on one lucky
        # threshold. At every one of these budgets only one file's content
        # can fit — it must always be the nearest (web/AGENTS.md), never the
        # root (CLAUDE.md).
        make_tree(self.root, {
            "CLAUDE.md": "rootrootroot" * 600 + "\n",
            "web/AGENTS.md": "nearnearnear" * 600 + "\n",
        })
        ranges = {"web/app/x.py": [(1, 1)]}
        for budget in (4400, 4200, 4000):
            with self.subTest(budget=budget):
                out = review.pack_conventions(self.root, ranges, self.acc(conventions=budget))
                self.assertIn("truncated", out)
                self.assertIn("nearnearnear", out)
                self.assertNotIn("rootrootroot", out)

    def test_a_document_containing_a_triple_backtick_block_is_not_terminated_early(self):
        # A CLAUDE.md documenting its own fenced example is routine (the
        # real golf-tracker one has several). A fixed 3-backtick wrapper
        # would be closed by the document's own ``` line, spilling the rest
        # of the document — including its headings — out unfenced.
        doc = "# Title\n\nExample:\n\n```\ncode here\n```\n\nMore text after the fence.\n"
        make_tree(self.root, {"CLAUDE.md": doc})
        out = review.pack_conventions(self.root, {"src/a.py": [(1, 1)]}, self.acc())
        fence = self._fence_line_after(out, "### CLAUDE.md\n")
        self.assertEqual(fence, "````")  # longest run in doc is 3, so wrapper is 4
        self.assertEqual(out.count(fence), 2)
        start = out.index(fence) + len(fence)
        end = out.index(fence, start)
        self.assertIn("More text after the fence.", out[start:end])

    def test_a_document_containing_a_four_backtick_block_gets_a_five_backtick_wrapper(self):
        # The rule must not be "always use four" — it must outrun whatever
        # the longest run actually present is, however long that is.
        doc = "# Title\n\n````\nnested example with ``` inside\n````\n\nTrailer text.\n"
        make_tree(self.root, {"AGENTS.md": doc})
        out = review.pack_conventions(self.root, {"src/a.py": [(1, 1)]}, self.acc())
        fence = self._fence_line_after(out, "### AGENTS.md\n")
        self.assertEqual(fence, "`````")  # longest run in doc is 4, so wrapper is 5
        self.assertEqual(out.count(fence), 2)
        start = out.index(fence) + len(fence)
        end = out.index(fence, start)
        self.assertIn("Trailer text.", out[start:end])

    def test_a_documents_own_headings_are_fenced_out_of_prompt_structure(self):
        # The core defect: a document's own #/## headings must not read as
        # more prompt structure at the same level as the pack's own
        # "## Repo conventions" heading (or the file-name "### rel" heading).
        doc = "# CLAUDE.md\n\n## Project status\n\n## Conventions\n\nUse tabs.\n"
        make_tree(self.root, {"CLAUDE.md": doc})
        out = review.pack_conventions(self.root, {"src/a.py": [(1, 1)]}, self.acc())
        fence = self._fence_line_after(out, "### CLAUDE.md\n")
        self.assertEqual(fence, "```")  # no backticks in the doc itself
        self.assertEqual(out.count(fence), 2)
        start = out.index(fence) + len(fence)
        end = out.index(fence, start)
        inside, outside = out[start:end], out[:start] + out[end + len(fence):]
        self.assertIn("\n## Conventions\n", inside)
        self.assertIn("# CLAUDE.md\n", inside)
        self.assertNotIn("\n## Conventions\n", outside)
        self.assertNotIn("\n# CLAUDE.md\n", outside)
        # The pack's own structural headings are untouched.
        self.assertIn("## Repo conventions", outside)
        self.assertIn("### CLAUDE.md", outside)

    def test_multiple_documents_are_each_delimited_with_their_own_fence(self):
        # Each selected document gets its own fence sized to its own
        # content — one file's embedded fence must not force a wider
        # wrapper on a different file that doesn't need one.
        make_tree(self.root, {
            "CLAUDE.md": "Plain rules, no fences here.\n",
            "web/AGENTS.md": "Has an example:\n\n```\nexample code\n```\n\nAfter.\n",
        })
        out = review.pack_conventions(self.root, {"web/app/x.py": [(1, 1)]}, self.acc())
        self.assertEqual(self._fence_line_after(out, "### web/AGENTS.md\n"), "````")
        self.assertEqual(self._fence_line_after(out, "### CLAUDE.md\n"), "```")

    def test_no_convention_files_and_no_readme_yields_an_empty_section(self):
        make_tree(self.root, {"src/a.py": "x = 1\n"})
        out = review.pack_conventions(self.root, {"src/a.py": [(1, 1)]}, self.acc())
        self.assertEqual(out, "")

    def test_no_checkout_yields_an_empty_section(self):
        self.assertEqual(review.pack_conventions(None, {}, self.acc()), "")

    def test_the_emitted_order_is_identical_across_python_hash_seeds(self):
        # The direct regression guard for this bug's root cause: `own_dirs`
        # and `prefixes` are sets, so without a final deterministic sort key
        # the surviving order (and therefore what a tight budget keeps or
        # drops) could depend on CPython's per-process string-hash
        # randomisation. Six branches at three different depths is wide
        # enough that a hash-seed-dependent order would actually show up as
        # a different result, not just a coincidentally-stable one.
        files = {"CLAUDE.md": "root\n"}
        ranges = {}
        for i in range(6):
            d = f"team{i:02d}/svc{i:02d}/deep{i:02d}"
            files[f"{d}/AGENTS.md"] = f"rules {i}\n"
            ranges[f"{d}/mod.py"] = [(1, 1)]
        make_tree(self.root, files)

        review_dir = str(pathlib.Path(review.__file__).resolve().parent)
        script = (
            "import sys, pathlib\n"
            f"sys.path.insert(0, {review_dir!r})\n"
            "import review\n"
            f"ranges = {ranges!r}\n"
            "acc = review.Accounting({'changed_files': 1, 'call_sites': 1,\n"
            "                         'conventions': 100000, 'requirements': 1, 'tree': 1})\n"
            f"out = review.pack_conventions(pathlib.Path({str(self.root)!r}), ranges, acc)\n"
            "sys.stdout.write(out)\n"
        )
        outputs = []
        for seed in ("0", "1", "42"):
            proc = subprocess.run(
                [sys.executable, "-c", script],
                env={**os.environ, "PYTHONHASHSEED": seed},
                capture_output=True, text=True, check=True,
            )
            outputs.append(proc.stdout)
        self.assertTrue(outputs[0], "the fixture produced nothing; it proves nothing")
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0], outputs[2])


class TestPackTree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.cfg = dict(review.DEFAULTS)
        self.addCleanup(self.tmp.cleanup)

    def acc(self, tree=6000):
        return review.Accounting({"changed_files": 1, "call_sites": 1, "conventions": 1,
                                  "requirements": 1, "tree": tree})

    def _paths(self, out):
        m = re.search(r"```\n(.*?)\n```", out, re.S)
        return set(m.group(1).splitlines()) if m else set()

    def test_siblings_of_a_changed_file_are_listed_in_full(self):
        make_tree(self.root, {
            "src/a.py": "", "src/b.py": "", "src/helpers.py": "",
            "far/away/deep/x.py": "",
        })
        out = review.pack_tree(self.root, {"src/a.py": [(1, 1)]}, self.cfg, self.acc())
        self.assertIn("src/helpers.py", out)

    def test_distant_deep_paths_are_pruned(self):
        make_tree(self.root, {"src/a.py": "", "far/away/deep/x.py": ""})
        out = review.pack_tree(self.root, {"src/a.py": [(1, 1)]}, self.cfg, self.acc())
        self.assertNotIn("far/away/deep/x.py", out)

    def test_shallow_paths_elsewhere_are_kept(self):
        make_tree(self.root, {"src/a.py": "", "Makefile": ""})
        out = review.pack_tree(self.root, {"src/a.py": [(1, 1)]}, self.cfg, self.acc())
        self.assertIn("Makefile", out)

    def test_pruning_keeps_exactly_the_near_and_shallow_paths(self):
        # Real depth and shape: a directory the diff touches (kept in full even
        # where it goes two levels deep), an unrelated directory just as deep
        # (pruned), and a scatter of shallow non-code paths elsewhere (kept).
        # A two-file fixture cannot exercise this — it can only ever pass or
        # fail uniformly.
        make_tree(self.root, {
            "src/pkg/a.py": "x = 1\n",
            "src/pkg/b.py": "x = 2\n",
            "src/pkg/sub/deep/c.py": "x = 3\n",
            "unrelated/far/away/x.py": "x = 4\n",
            "README.md": "readme\n",
            "Makefile": "all:\n",
            "config/settings.yaml": "k: v\n",
            "docs/deep/nested/guide.md": "guide\n",
        })
        out = review.pack_tree(self.root, {"src/pkg/a.py": [(1, 1)]}, self.cfg, self.acc())
        self.assertEqual(self._paths(out), {
            "src/pkg/a.py", "src/pkg/b.py",
            "README.md", "Makefile", "config/settings.yaml",
        })

    def test_non_code_paths_are_listed_deliberately_unlike_walk_source(self):
        # pack_tree's whole purpose is "what does this repo already have" —
        # restricting it to CODE_SUFFIXES (as walk_source does, for the
        # call-site grep's benefit) would silently drop README/Makefile/config
        # paths, which are exactly the paths that answer that question.
        make_tree(self.root, {"src/a.py": "x = 1\n", "Makefile": "all:\n", "README.md": "hi\n"})
        out = review.pack_tree(self.root, {"src/a.py": [(1, 1)]}, self.cfg, self.acc())
        self.assertEqual(self._paths(out), {"src/a.py", "Makefile", "README.md"})

    def test_ignore_paths_are_excluded_even_when_shallow_or_near(self):
        make_tree(self.root, {
            "src/pkg/a.py": "x = 1\n",
            "src/pkg/thing.lock": "lock\n",
            "package-lock.json": "{}\n",
            "vendor/generated/blob.py": "x = 1\n",
        })
        out = review.pack_tree(self.root, {"src/pkg/a.py": [(1, 1)]}, self.cfg, self.acc())
        self.assertEqual(self._paths(out), {"src/pkg/a.py"})

    def test_git_directory_is_never_listed(self):
        make_tree(self.root, {"src/a.py": "x = 1\n", ".git/HEAD": "ref: refs/heads/main\n"})
        out = review.pack_tree(self.root, {"src/a.py": [(1, 1)]}, self.cfg, self.acc())
        self.assertNotIn(".git", out)

    def test_truncation_is_marked_in_band_when_the_tree_exceeds_budget(self):
        # 400 shallow files comfortably exceed a 200-character budget; a
        # uniform tiny fixture against a huge budget would never exercise
        # this branch at all.
        make_tree(self.root, {f"top{i:03d}.py": "" for i in range(400)})
        out = review.pack_tree(self.root, {}, self.cfg, self.acc(tree=200))
        self.assertIn("truncated", out)
        # The cut lands inside the listing's own fence; leaving it open would
        # quote the rest of the prompt. See TestFenceBalanceUnderTruncation.
        self.assertIsNone(unclosed_fence(out))

    def test_no_checkout_yields_an_empty_section(self):
        self.assertEqual(review.pack_tree(None, {}, self.cfg, self.acc()), "")


# ── C1: no cut may leave a fence open, in any section, at any budget ─────────
#
# One swept property, not a spot check per section. Every section is fenced
# somewhere and every section is cut at a raw character offset against its own
# budget, so "the marker appeared" is not the interesting assertion: an
# unclosed fence swallows everything build_lens_prompt appends after the pack —
# the remaining sections, `lens: <name>`, the whole lens brief, and LENS_TAIL's
# anchoring rule and "Return only the JSON envelope" — into one quoted block.

FENCE_DIFF = (
    "diff --git a/src/pkg/app.py b/src/pkg/app.py\n"
    "--- a/src/pkg/app.py\n"
    "+++ b/src/pkg/app.py\n"
    "@@ -1,3 +1,4 @@\n"
    " import os\n"
    "+def render_report_block(rows):\n"
    "     return rows\n"
)

# A source file that documents a fenced example, which is ordinary in real code.
FENCED_SOURCE = (
    "import os\n"
    "def render_report_block(rows):\n"
    '    """Render rows.\n\n'
    "    ```\n"
    "    render_report_block([])\n"
    "    ```\n"
    '    """\n'
    "    return rows\n"
) + "".join(f"FILLER_LINE_{i} = {i}\n" for i in range(120))

# A conventions document holding both a three- and a four-backtick block, so
# the fence bookkeeping cannot get away with counting occurrences.
FENCED_CONVENTIONS = (
    "# Conventions\n\n## Style\n\n```\nexample()\n```\n\n"
    "## Nested\n\n````\n```\ninner\n```\n````\n\n"
) + "".join(f"- convention rule number {i}\n" for i in range(120))

FENCED_BODY = (
    "Reworks the report block.\n\n```python\n"
    + "".join(f"sample_call({i})\n" for i in range(120))
    + "```\n\nSee the issue for the rest.\n"
)


class TestFenceBalanceUnderTruncation(unittest.TestCase):
    """C1: `Accounting.add` cuts at a raw offset and knows nothing about
    structure. Fixed once in `_capped`, so it is asserted once, here, over
    every section and over the assembled prompt."""

    @classmethod
    def setUpClass(cls):
        review.DOC = review.Doctrine(
            pathlib.Path(review.__file__).resolve().parent / "doctrine")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        files = {
            "src/pkg/app.py": FENCED_SOURCE,
            "src/pkg/CLAUDE.md": FENCED_CONVENTIONS,
            "CLAUDE.md": FENCED_CONVENTIONS,
        }
        for i in range(8):
            files[f"web/caller{i}.py"] = "".join(
                f'render_report_block([f"`{j}`"])\n' for j in range(4))
        for i in range(30):
            files[f"top_level_file_{i:03d}.py"] = "x = 1\n"
        make_tree(self.root, files)
        self.cfg = dict(review.DEFAULTS)
        self.ranges = review.diff_paths(FENCE_DIFF)
        self.pr = {"number": 7, "title": "t", "body": FENCED_BODY,
                   "head": {"sha": "abc1234"}, "_rounds": 0, "_prior_body": None}

    def sections(self, limit):
        """Every section rendered at the same per-part budget `limit`."""
        parts = ("changed_files", "call_sites", "conventions", "requirements", "tree")
        acc = review.Accounting({p: limit for p in parts})
        return {
            "changed_files": review.pack_changed_files(
                self.root, None, "o/r", "sha", self.ranges, self.cfg, acc),
            "call_sites": review.pack_call_sites(
                self.root, FENCE_DIFF, self.ranges, self.cfg, acc),
            "conventions": review.pack_conventions(self.root, self.ranges, acc),
            "tree": review.pack_tree(self.root, self.ranges, self.cfg, acc),
            "requirements": review.resolve_requirements(None, "o/r", self.pr, acc),
        }, acc

    def test_no_section_ends_inside_an_open_fence_at_any_budget(self):
        # Swept rather than sampled: which fence a cut lands inside is a
        # function of the budget, so a fixed budget only ever proves one
        # offset. The step deliberately does not divide any section's length.
        for limit in list(range(0, 400, 7)) + list(range(400, 6001, 143)):
            text, _ = self.sections(limit)
            for part, out in text.items():
                with self.subTest(limit=limit, part=part):
                    self.assertIsNone(
                        unclosed_fence(out),
                        f"{part} at limit {limit} left a fence open:\n{out[-200:]!r}")

    def test_a_truncated_section_still_carries_its_marker_in_band(self):
        # Closing the fence costs characters, and those characters must not come
        # out of the marker: truncation stays visible at every budget that can
        # hold a single character of it.
        for limit in list(range(1, 400, 7)) + list(range(400, 6001, 143)):
            text, acc = self.sections(limit)
            for part in acc.truncated:
                with self.subTest(limit=limit, part=part):
                    self.assertIn(
                        "…", text[part],
                        f"{part} at limit {limit} was truncated with no marker")

    def test_the_assembled_lens_prompt_never_ends_inside_an_open_fence(self):
        # The property that actually matters: the lens must never read its own
        # brief or LENS_TAIL as quoted code. Asserted on the whole prompt —
        # doctrine, shared block and tail — not on the pack alone.
        for total in list(range(0, 4001, 173)) + [8300, 20000, 83000]:
            cfg = dict(review.DEFAULTS)
            cfg["max_context_chars"] = total
            with review.build_context(
                None, "o/r", self.pr, FENCE_DIFF, cfg, enabled=True,
                worktree=str(self.root),
            ) as ctx:
                pass
            system, user = review.build_lens_prompt(
                "craft", self.pr, "o/r", FENCE_DIFF, ctx.requirements, ctx.pack)
            assembled = "\n\n".join(
                [b["text"] for b in system] + [b["text"] for b in user])
            with self.subTest(total=total):
                self.assertIsNone(
                    unclosed_fence(ctx.pack), f"pack left a fence open at {total}")
                self.assertIsNone(
                    unclosed_fence(ctx.requirements),
                    f"requirements left a fence open at {total}")
                self.assertIsNone(
                    unclosed_fence(assembled),
                    f"assembled prompt left a fence open at {total}")
                # And the tail is really outside every fence, not merely present.
                self.assertIn(review.LENS_TAIL, assembled)
                self.assertIsNone(
                    unclosed_fence(assembled[:assembled.index(review.LENS_TAIL)]),
                    f"LENS_TAIL is inside an open fence at {total}")


class TestClipHit(unittest.TestCase):
    """A minified `.js` line is one line and may be half a megabyte of it —
    `walk_source` admits the file, so the clip is what keeps a single hit from
    spending the whole call-sites budget."""

    def test_a_short_line_is_passed_through_stripped(self):
        self.assertEqual(review._clip_hit("  call_it()  "), "call_it()")

    def test_a_long_line_is_clipped_and_marked(self):
        out = review._clip_hit("call_it(" + "x" * 5000 + ")")
        self.assertLessEqual(len(out), review.MAX_HIT_CHARS + 20)
        self.assertIn("…", out)

    def test_a_minified_hit_cannot_blow_the_section_budget_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            make_tree(root, {
                "src/service.py": "x = 1\n",
                "web/bundle.js": "var a=1;" + "".join(
                    f'require("src/service");z{i}=1;' for i in range(4000)) + "\n",
            })
            acc = review.Accounting({"changed_files": 1, "call_sites": 14940,
                                     "conventions": 1, "requirements": 1, "tree": 1})
            out = review.pack_call_sites(
                root, "--- a/src/service.py\n+++ b/src/service.py\n@@ -1,1 +1,1 @@\n+x = 2\n",
                {"src/service.py": [(1, 1)]}, dict(review.DEFAULTS), acc)
            self.assertIn("web/bundle.js", out)
            self.assertNotIn("call_sites", acc.truncated)


if __name__ == "__main__":
    unittest.main()
