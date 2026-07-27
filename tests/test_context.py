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


class TestAccounting(unittest.TestCase):
    def test_text_within_budget_passes_through_unchanged(self):
        acc = review.Accounting({"tree": 100})
        self.assertEqual(acc.add("tree", "short"), "short")

    def test_text_over_budget_is_truncated_with_a_marker(self):
        acc = review.Accounting({"tree": 40})
        out = acc.add("tree", "x" * 200)
        self.assertLess(len(out), 200)
        self.assertIn("truncated", out)

    def test_usage_is_recorded_per_part(self):
        acc = review.Accounting({"tree": 100, "conventions": 100})
        acc.add("tree", "abc")
        self.assertEqual(acc.used["tree"], 3)
        self.assertEqual(acc.used["conventions"], 0)


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


if __name__ == "__main__":
    unittest.main()
