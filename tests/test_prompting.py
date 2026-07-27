"""Prompt assembly and dispatch. No network: nothing here calls a model."""

import pathlib
import sys
import threading
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import review  # noqa: E402


class TestSeg(unittest.TestCase):
    def test_plain_block_carries_no_cache_control(self):
        self.assertEqual(review.seg("hello"), {"type": "text", "text": "hello"})

    def test_cache_block_carries_the_ephemeral_marker(self):
        self.assertEqual(
            review.seg("hello", cache=True),
            {"type": "text", "text": "hello", "cache_control": {"type": "ephemeral"}},
        )

    def test_cache_marker_is_suppressed_when_caching_is_disabled(self):
        original = review.CACHE_ENABLED
        review.CACHE_ENABLED = False
        try:
            self.assertEqual(review.seg("hello", cache=True), {"type": "text", "text": "hello"})
        finally:
            review.CACHE_ENABLED = original


class TestCompletionPayload(unittest.TestCase):
    SCHEMA = {"type": "object"}

    def payload(self, system, user):
        return review.completion_payload("m/model", system, user, self.SCHEMA, "lens:craft")

    def test_a_string_is_wrapped_into_one_text_block(self):
        p = self.payload("sys", "usr")
        self.assertEqual(p["messages"][0]["content"], [{"type": "text", "text": "sys"}])
        self.assertEqual(p["messages"][1]["content"], [{"type": "text", "text": "usr"}])

    def test_block_arrays_pass_through_untouched(self):
        blocks = [review.seg("a", cache=True), review.seg("b")]
        p = self.payload(blocks, "usr")
        self.assertEqual(p["messages"][0]["content"], blocks)

    def test_schema_name_is_sanitised_for_the_api(self):
        p = self.payload("sys", "usr")
        self.assertEqual(p["response_format"]["json_schema"]["name"], "lens_craft")

    def test_routing_and_determinism_settings_are_preserved(self):
        p = self.payload("sys", "usr")
        self.assertEqual(p["temperature"], 0)
        self.assertTrue(p["provider"]["require_parameters"])
        self.assertTrue(p["response_format"]["json_schema"]["strict"])


class TestStripFence(unittest.TestCase):
    """A provider can honour response_format and still fence its output."""

    def test_bare_json_is_returned_unchanged(self):
        self.assertEqual(review.strip_fence('{"a": 1}'), '{"a": 1}')

    def test_a_labelled_fence_is_removed(self):
        self.assertEqual(review.strip_fence('```json\n{"a": 1}\n```'), '{"a": 1}')

    def test_an_unlabelled_fence_is_removed(self):
        self.assertEqual(review.strip_fence('```\n{"a": 1}\n```'), '{"a": 1}')

    def test_an_unterminated_fence_is_still_stripped(self):
        self.assertEqual(review.strip_fence('```json\n{"a": 1}'), '{"a": 1}')

    def test_surrounding_whitespace_is_removed(self):
        self.assertEqual(review.strip_fence('\n\n```json\n{"a": 1}\n```\n\n'), '{"a": 1}')

    def test_a_fence_inside_a_string_value_survives(self):
        # Only the outermost wrapper is stripped; lens findings quote code.
        payload = '{"fix": "use ```python blocks"}'
        self.assertEqual(review.strip_fence(payload), payload)


DIFF = """\
diff --git a/src/foo.py b/src/foo.py
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,3 +1,4 @@
 import os
+import sys

 def main():
"""

PR = {
    "number": 42,
    "title": "Add sys import",
    "body": "Because we need it.",
    "head": {"sha": "abc1234"},
    "_rounds": 0,
    "_prior_body": None,
}


class TestLensPromptBlocks(unittest.TestCase):
    """Blocks 1 and 2 are the cacheable prefix and must not vary by lens."""

    @classmethod
    def setUpClass(cls):
        review.DOC = review.Doctrine(pathlib.Path(review.__file__).resolve().parent / "doctrine")

    def build(self, lens, pack="## Context\nsome context\n"):
        return review.build_lens_prompt(lens, PR, "o/r", DIFF, "the requirements", pack)

    def test_system_is_one_cached_block(self):
        system, _ = self.build("craft")
        self.assertEqual(len(system), 1)
        self.assertIn("cache_control", system[0])

    def test_user_is_a_cached_block_then_an_uncached_tail(self):
        _, user = self.build("craft")
        self.assertEqual(len(user), 2)
        self.assertIn("cache_control", user[0])
        self.assertNotIn("cache_control", user[1])

    def test_cacheable_blocks_are_byte_identical_across_lenses(self):
        built = {lens: self.build(lens) for lens in review.LENSES}
        systems = {s[0]["text"] for s, _ in built.values()}
        shared = {u[0]["text"] for _, u in built.values()}
        self.assertEqual(len(systems), 1, "system block differs between lenses")
        self.assertEqual(len(shared), 1, "shared user block differs between lenses")

    def test_the_lens_marker_appears_only_in_the_tail(self):
        for lens in review.LENSES:
            system, user = self.build(lens)
            cacheable = system[0]["text"] + user[0]["text"]
            self.assertNotIn(f"lens: {lens}", cacheable)
            self.assertIn(f"lens: {lens}", user[1]["text"])

    def test_the_lens_brief_appears_only_in_the_tail(self):
        for lens in review.LENSES:
            system, user = self.build(lens)
            brief = review.DOC(f"lenses/{lens}.md")
            self.assertNotIn(brief, system[0]["text"] + user[0]["text"])
            self.assertIn(brief, user[1]["text"])

    def test_shared_doctrine_is_in_the_system_block(self):
        system, _ = self.build("craft")
        self.assertIn(review.DOC("lenses/_shared.md"), system[0]["text"])
        self.assertIn(review.DOC("agents/pr-review-lens.md"), system[0]["text"])

    def test_diff_and_pack_are_in_the_cached_user_block(self):
        _, user = self.build("craft")
        self.assertIn(DIFF, user[0]["text"])
        self.assertIn("some context", user[0]["text"])

    def test_requirements_precede_the_diff(self):
        _, user = self.build("craft")
        text = user[0]["text"]
        self.assertLess(text.index("the requirements"), text.index(DIFF))

    def test_an_absent_pack_leaves_no_dangling_heading(self):
        _, user = self.build("craft", pack="")
        self.assertNotIn("## Context", user[0]["text"])


class TestDispatchLenses(unittest.TestCase):
    def test_the_first_lens_finishes_before_the_others_start(self):
        events = []

        def runner(lens):
            events.append(("start", lens))
            time.sleep(0.05)
            events.append(("end", lens))
            return {"lens": lens}

        review.dispatch_lenses(("a", "b", "c"), runner, stagger=True)
        self.assertEqual(events[0], ("start", "a"))
        self.assertEqual(events[1], ("end", "a"))

    def test_results_come_back_in_lens_order_not_completion_order(self):
        def runner(lens):
            time.sleep({"a": 0.06, "b": 0.02, "c": 0.04}[lens])
            return {"lens": lens}

        out = review.dispatch_lenses(("a", "b", "c"), runner, stagger=True)
        self.assertEqual([e["lens"] for e in out], ["a", "b", "c"])

    def test_the_trailing_lenses_run_concurrently(self):
        barrier = threading.Barrier(2, timeout=2)

        def runner(lens):
            if lens != "a":
                barrier.wait()  # BrokenBarrierError unless b and c overlap
            return {"lens": lens}

        review.dispatch_lenses(("a", "b", "c"), runner, stagger=True)

    def test_unstaggered_dispatch_runs_every_lens_concurrently(self):
        barrier = threading.Barrier(3, timeout=2)

        def runner(lens):
            barrier.wait()
            return {"lens": lens}

        review.dispatch_lenses(("a", "b", "c"), runner, stagger=False)

    def test_a_single_lens_needs_no_staggering(self):
        out = review.dispatch_lenses(("a",), lambda lens: {"lens": lens}, stagger=True)
        self.assertEqual(out, [{"lens": "a"}])

    def test_a_runner_exception_propagates_rather_than_being_swallowed(self):
        def runner(lens):
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            review.dispatch_lenses(("a",), runner, stagger=True)


if __name__ == "__main__":
    unittest.main()
