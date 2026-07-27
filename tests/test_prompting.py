"""Prompt assembly and dispatch. No network: nothing here calls a model."""

import pathlib
import sys
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


if __name__ == "__main__":
    unittest.main()
