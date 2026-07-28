"""Prompt assembly and dispatch. No network: nothing here calls a model."""

import argparse
import os
import pathlib
import sys
import threading
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import review  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_context import unclosed_fence  # noqa: E402  (the independent fence checker)


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

    def test_the_deployment_tail_is_present_in_the_assembled_prompt(self):
        # Deleting LENS_TAIL from the prompt entirely was a green mutation. It is
        # what tells a lens it has no tools, that an absent section is code it
        # has not seen, and that every finding must anchor to a diff line — none
        # of which the upstream doctrine says, because upstream had a worktree.
        for lens in review.LENSES:
            with self.subTest(lens=lens):
                system, user = self.build(lens)
                assembled = "".join(b["text"] for b in system + user)
                self.assertIn(review.LENS_TAIL, assembled)

    def test_the_porting_note_precedes_the_doctrine_it_overrides(self):
        # Asserting each file is present with two assertIns leaves swapping them
        # green, and the order is the point: agents/pr-review-lens.md opens with
        # the porting note that overrides the doctrine below it (no tools, no
        # worktree, no merging — see CLAUDE.md). Doctrine first would mean the
        # lens reads the overridden rules as final.
        system, _ = self.build("craft")
        text = system[0]["text"]
        self.assertLess(
            text.index(review.DOC("agents/pr-review-lens.md")),
            text.index(review.DOC("lenses/_shared.md")),
            "the porting note must come before the doctrine it overrides",
        )


# The diff itself can carry markdown fences — an ordinary documentation PR,
# not a crafted attack. A context line renders as " ```" (single leading
# space), an added/removed line as "+```"/"-```". All three must be counted
# when sizing the wrapper around the whole diff.
FENCE_ALL_MARKERS_DIFF = (
    "diff --git a/docs/notes.md b/docs/notes.md\n"
    "--- a/docs/notes.md\n"
    "+++ b/docs/notes.md\n"
    "@@ -1,4 +1,4 @@\n"
    " # Notes\n"
    " ```\n"
    "-old example\n"
    "-```\n"
    "+new example\n"
    "+```\n"
)

# A nested example escaped with four backticks, same as CLAUDE.md's own
# convention docs — the wrapper must outrun this, not just upgrade to four.
FOUR_BACKTICK_FENCE_DIFF = (
    "diff --git a/docs/notes.md b/docs/notes.md\n"
    "--- a/docs/notes.md\n"
    "+++ b/docs/notes.md\n"
    "@@ -1,3 +1,4 @@\n"
    " # Notes\n"
    " ````\n"
    "+new line inside the nested example\n"
    " ````\n"
)

# The reproducing case: a hunk showing only a fence's opener, never its
# closer (an ordinary `gh pr diff` context window). One occurrence — odd.
ODD_FENCE_DIFF = (
    "diff --git a/docs/notes.md b/docs/notes.md\n"
    "--- a/docs/notes.md\n"
    "+++ b/docs/notes.md\n"
    "@@ -10,3 +10,4 @@\n"
    " ```\n"
    " example()\n"
    "+trailing comment\n"
)

# Both the opener and the closer are unchanged context lines — two
# occurrences, even.
EVEN_FENCE_DIFF = (
    "diff --git a/docs/notes.md b/docs/notes.md\n"
    "--- a/docs/notes.md\n"
    "+++ b/docs/notes.md\n"
    "@@ -1,5 +1,5 @@\n"
    " # Notes\n"
    " ```\n"
    "-example old\n"
    "+example new\n"
    " ```\n"
)


class TestDiffFenceWrapping(unittest.TestCase):
    """The diff wrapped into the lens prompt (`## Diff ... ```diff ... ``` `)
    can itself contain markdown fences — this repo's own docs are full of
    them, so an ordinary documentation PR reaches this. A fixed 3-backtick
    wrapper is closed early by any embedded 3-or-more-backtick run, which
    swallows everything build_lens_prompt appends after it: the rest of the
    context pack, the lens brief, and LENS_TAIL. See CLAUDE.md."""

    def setUp(self):
        # The real doctrine's own fenced examples (lenses/_shared.md and
        # each lens brief's ```json block) are each independently balanced,
        # so they can coincidentally re-close a fence a broken diff wrapper
        # left open — masking the defect at the point LENS_TAIL is checked,
        # purely by luck of doc content. A backtick-free stand-in removes
        # that confound and makes the diff wrapper the only variable.
        real_doc = getattr(review, "DOC", None)
        review.DOC = lambda path: f"(doctrine stand-in for {path}, no backticks)"
        if real_doc is None:
            self.addCleanup(delattr, review, "DOC")
        else:
            self.addCleanup(setattr, review, "DOC", real_doc)

    def assembled(self, diff, pack=""):
        system, user = review.build_lens_prompt("craft", PR, "o/r", diff, "the requirements", pack)
        return "\n\n".join(b["text"] for b in system + user)

    def assert_balanced_and_tail_outside(self, diff):
        text = self.assembled(diff)
        self.assertIsNone(unclosed_fence(text), f"prompt left a fence open:\n{text[-200:]!r}")
        self.assertIn(review.LENS_TAIL, text)
        self.assertIsNone(
            unclosed_fence(text[: text.index(review.LENS_TAIL)]),
            "LENS_TAIL sits inside an open fence",
        )

    def test_a_three_backtick_fence_on_context_added_and_removed_lines_stays_balanced(self):
        self.assert_balanced_and_tail_outside(FENCE_ALL_MARKERS_DIFF)

    def test_a_four_backtick_fence_stays_balanced_not_merely_widened_to_four(self):
        self.assert_balanced_and_tail_outside(FOUR_BACKTICK_FENCE_DIFF)

    def test_a_diff_with_no_backticks_still_gets_a_plain_three_backtick_wrapper(self):
        # No gratuitous widening: nothing in the diff forces a longer fence.
        _, user = review.build_lens_prompt("craft", PR, "o/r", DIFF, "the requirements", "")
        self.assertIn(f"```diff\n{DIFF}\n```\n", user[0]["text"])

    def test_an_odd_number_of_fence_lines_in_the_diff_stays_balanced(self):
        self.assert_balanced_and_tail_outside(ODD_FENCE_DIFF)

    def test_an_even_number_of_fence_lines_in_the_diff_stays_balanced(self):
        self.assert_balanced_and_tail_outside(EVEN_FENCE_DIFF)


def flat(content) -> str:
    """A prompt argument as text: openrouter takes either a string or blocks."""
    return content if isinstance(content, str) else "".join(b["text"] for b in content)
class TestAdjudicatePrompt(unittest.TestCase):
    """The branch's most load-bearing structural invariant: the adjudicator sees
    the lens envelopes, the PR body, the prior review body and the resolved
    requirements — never the diff, never ctx.pack (see CLAUDE.md and
    doctrine/agents/pr-review-verdict.md). adjudicate() appeared in no test at
    all, so appending the diff to its user message was a green mutation."""

    DIFF_TOKEN = "SENTINEL_ONLY_IN_THE_DIFF"
    PACK_TOKEN = "SENTINEL_ONLY_IN_THE_PACK"

    @classmethod
    def setUpClass(cls):
        review.DOC = review.Doctrine(
            pathlib.Path(review.__file__).resolve().parent / "doctrine")

    def pr(self):
        return dict(PR, body="the PR body itself",
                    _prior_body="what round 1 recommended", _rounds=1)

    def capture(self):
        """adjudicate() with the model call stubbed out, returning its prompt."""
        seen = {}

        def fake(model, system, user, schema, label=None):
            seen["model"] = model
            seen["system"] = flat(system)
            seen["user"] = flat(user)
            return {"verdict": "approve"}

        real, review.openrouter = review.openrouter, fake
        try:
            review.adjudicate(
                self.pr(), "o/r",
                [{"lens": "craft", "findings": [{"note": "a lens said this"}]}],
                "the resolved requirements", "some/model",
            )
        finally:
            review.openrouter = real
        return seen

    def test_the_four_things_it_must_see_are_all_in_its_user_message(self):
        user = self.capture()["user"]
        self.assertIn("a lens said this", user)                     # lens envelopes
        self.assertIn("the PR body itself", user)                   # PR body
        self.assertIn("what round 1 recommended", user)             # prior review body
        self.assertIn("the resolved requirements", user)            # resolved requirements

    def test_its_user_message_carries_exactly_these_sections_and_no_others(self):
        # An exact heading set, not four assertIns: a "## Diff" section added
        # here is the whole failure this invariant exists to prevent, and only
        # an exact set notices a new one.
        user = self.capture()["user"]
        self.assertEqual(
            [ln for ln in user.splitlines() if ln.startswith("## ")],
            ["## PR body", "## Resolved requirements",
             "## Prior recommendations", "## Lens envelopes"],
        )

    def test_neither_the_diff_nor_the_pack_reaches_the_verdict_prompt(self):
        # Asserted through run_panel, where a real diff and a real pack are both
        # in scope — the only place a future "helpful" change could pass either
        # one down, whatever route it took to get there.
        prompts = []

        def fake(model, system, user, schema, label=None):
            prompts.append((label, flat(system) + flat(user)))
            if label == "verdict":
                return {"verdict": "approve", "blocker_count": 0,
                        "body": "<!-- pr-reviewer: verdict=approve round=2 sha=abc1234 -->\nok"}
            return {"lens": label.split(":")[1], "status": "ok", "findings": []}

        diff = DIFF.replace("import sys", f"import sys  # {self.DIFF_TOKEN}")
        ctx = review.Context("the resolved requirements")
        ctx.pack = f"## Changed files at head\n{self.PACK_TOKEN}\n"
        opts = argparse.Namespace(lens=None, model_lens="m/lens",
                                  model_verdict="m/verdict", save=None)

        real, review.openrouter = review.openrouter, fake
        try:
            verdict = review.run_panel(self.pr(), "o/r", diff, ctx, opts)
        finally:
            review.openrouter = real

        self.assertEqual(verdict["verdict"], "approve")
        sent = dict(prompts)
        self.assertIn(self.DIFF_TOKEN, sent["lens:craft"])          # the lenses do see both
        self.assertIn(self.PACK_TOKEN, sent["lens:craft"])
        self.assertNotIn(self.DIFF_TOKEN, sent["verdict"])          # the adjudicator sees neither
        self.assertNotIn(self.PACK_TOKEN, sent["verdict"])

    def test_the_marker_contract_and_the_round_number_are_stated(self):
        user = self.capture()["user"]
        self.assertIn("<!-- pr-reviewer: verdict=", user)
        self.assertIn("round=2", user)                              # _rounds 1 -> round 2
        self.assertIn(PR["head"]["sha"][:7], user)

    def test_the_verdict_doctrine_is_the_system_prompt(self):
        seen = self.capture()
        self.assertIn(review.DOC("agents/pr-review-verdict.md"), seen["system"])
        self.assertIn(review.DOC("verdict.md"), seen["system"])

    def test_the_verdict_model_is_the_one_it_was_given(self):
        # Each model call names its own model so a cheap model reviews and a
        # stronger one adjudicates (CLAUDE.md); collapsing that is a real risk.
        self.assertEqual(self.capture()["model"], "some/model")


class TestResolvePost(unittest.TestCase):
    """Posting requires an explicit opt-in and --dry-run always wins."""

    def opts(self, **kw):
        return argparse.Namespace(**{"dry_run": False, "post": False, **kw})

    def setUp(self):
        self.before = os.environ.get("DRY_RUN")
        self.addCleanup(self.restore)

    def restore(self):
        if self.before is None:
            os.environ.pop("DRY_RUN", None)
        else:
            os.environ["DRY_RUN"] = self.before

    def test_dry_run_beats_post(self):
        os.environ.pop("DRY_RUN", None)
        self.assertFalse(review.resolve_post(self.opts(dry_run=True, post=True)))

    def test_an_unset_dry_run_env_does_not_post(self):
        os.environ.pop("DRY_RUN", None)
        self.assertFalse(review.resolve_post(self.opts()))

    def test_post_alone_posts(self):
        os.environ.pop("DRY_RUN", None)
        self.assertTrue(review.resolve_post(self.opts(post=True)))

    def test_dry_run_zero_in_the_env_posts(self):
        os.environ["DRY_RUN"] = "0"
        self.assertTrue(review.resolve_post(self.opts()))

    def test_dry_run_one_in_the_env_does_not_post(self):
        os.environ["DRY_RUN"] = "1"
        self.assertFalse(review.resolve_post(self.opts()))

    def test_dry_run_beats_a_posting_env(self):
        os.environ["DRY_RUN"] = "0"
        self.assertFalse(review.resolve_post(self.opts(dry_run=True)))

    def test_an_unrecognised_dry_run_value_does_not_post(self):
        # Posting is opt-in, so the allow-list is of the values that mean "post"
        # — never a deny-list of the ones that mean "don't". A typo in the
        # CronJob's env must fail safe.
        for value in ("", " ", "maybe", "off", "2"):
            with self.subTest(value=value):
                os.environ["DRY_RUN"] = value
                self.assertFalse(review.resolve_post(self.opts()))


class TestResolveCache(unittest.TestCase):
    """The CLI wins, so --no-cache is always an effective escape hatch."""

    def test_no_cache_beats_a_repo_config_asking_for_caching(self):
        opts = argparse.Namespace(no_cache=True)
        self.assertFalse(review.resolve_cache(opts, {"cache": True}))

    def test_a_repo_can_turn_caching_off(self):
        opts = argparse.Namespace(no_cache=False)
        self.assertFalse(review.resolve_cache(opts, {"cache": False}))

    def test_caching_is_on_by_default(self):
        opts = argparse.Namespace(no_cache=False)
        self.assertTrue(review.resolve_cache(opts, None))
        self.assertTrue(review.resolve_cache(opts, {}))


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
        # Under staggering, "a" always completes first, so the old timings
        # (a=0.06, b=0.02, c=0.04) made completion order a, b, c — identical to
        # lens order, which left `return list(results.values())` green. The
        # parallel pair is now timed so completion order is c, b: genuinely the
        # reverse of the requested order for every lens that races.
        def runner(lens):
            time.sleep({"a": 0.0, "b": 0.09, "c": 0.01}[lens])
            return {"lens": lens}

        out = review.dispatch_lenses(("a", "b", "c"), runner, stagger=True)
        self.assertEqual([e["lens"] for e in out], ["a", "b", "c"])

    def test_completion_order_really_is_the_reverse_of_lens_order(self):
        # The premise of the test above, asserted rather than assumed: if the
        # timings ever stop inverting the order, that test silently stops
        # testing anything.
        done = []

        def runner(lens):
            time.sleep({"a": 0.0, "b": 0.09, "c": 0.01}[lens])
            done.append(lens)
            return {"lens": lens}

        review.dispatch_lenses(("a", "b", "c"), runner, stagger=True)
        self.assertEqual(done, ["a", "c", "b"])

    def test_two_lenses_stagger_the_same_way_three_do(self):
        # `len(lenses) > 1` -> `> 2` survived: with two lenses the mutant runs
        # both in parallel, so both pay the cache-write premium and neither
        # reads — the exact cost staggering exists to avoid. Reached in the real
        # deployment by `--lens a --lens b`.
        events = []

        def runner(lens):
            events.append(("start", lens))
            time.sleep(0.05)
            events.append(("end", lens))
            return {"lens": lens}

        out = review.dispatch_lenses(("a", "b"), runner, stagger=True)
        self.assertEqual([e["lens"] for e in out], ["a", "b"])
        self.assertEqual(events[:2], [("start", "a"), ("end", "a")])

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
