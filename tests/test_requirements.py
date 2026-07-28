"""Requirements resolution. GitHub is stubbed; nothing here touches the network."""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import review  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_context import unclosed_fence  # noqa: E402  (the independent fence checker)


class FakeGitHub:
    """Just enough GitHub for resolve_requirements."""

    def __init__(self, issues=None, comments=None, fail=False):
        self.issues = issues or {}
        self.comments = comments or {}
        self.fail = fail
        self.calls = []

    def get(self, path):
        self.calls.append(path)
        if self.fail:
            raise RuntimeError("GitHub is down")
        if path.endswith("/comments"):
            return self.comments.get(path, [])
        return self.issues.get(path, {"title": "untitled", "body": ""})


def acc():
    return review.Accounting({"changed_files": 1, "call_sites": 1, "conventions": 1,
                              "requirements": 10000, "tree": 1})


class TestIssueRefs(unittest.TestCase):
    def test_a_bare_hash_reference_is_found(self):
        self.assertEqual(review.issue_refs("see #42 please", "o/r"), [("o/r", 42)])

    def test_a_closing_keyword_reference_is_found(self):
        self.assertEqual(review.issue_refs("Closes #7", "o/r"), [("o/r", 7)])

    def test_a_full_url_is_found_with_its_own_repo(self):
        self.assertEqual(
            review.issue_refs("https://github.com/other/proj/issues/9", "o/r"),
            [("other/proj", 9)],
        )

    def test_duplicates_collapse(self):
        self.assertEqual(review.issue_refs("#5 and #5 again", "o/r"), [("o/r", 5)])

    def test_at_most_five_references_are_returned(self):
        text = " ".join(f"#{n}" for n in range(1, 20))
        self.assertEqual(len(review.issue_refs(text, "o/r")), 5)

    def test_a_bare_number_is_not_a_reference(self):
        self.assertEqual(review.issue_refs("version 42 shipped", "o/r"), [])

    def test_a_hex_colour_is_not_a_reference(self):
        self.assertEqual(review.issue_refs("color: #ff0000", "o/r"), [])

    def test_empty_text_is_safe(self):
        self.assertEqual(review.issue_refs("", "o/r"), [])

    def test_hex_colours_and_malformed_numbers_are_rejected_exactly(self):
        # 0 and any leading zero are never real issue numbers, so these must
        # all come back empty. #123456 is a same-shaped false positive that
        # cannot be told apart from a real large issue number by pattern
        # alone — it is deliberately left matching and relies on the 404
        # backstop in resolve_requirements() to become harmless.
        cases = {
            "color: #000000": [],
            "color: #123456": [("o/r", 123456)],
            "#0": [],
            "#00042": [],
            "color: #ff0000": [],
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(review.issue_refs(text, "o/r"), expected)

    def test_real_references_still_resolve_exactly(self):
        # Guards against over-tightening the digit class in the same change
        # that rejects hex colours.
        self.assertEqual(review.issue_refs("#42", "o/r"), [("o/r", 42)])
        self.assertEqual(review.issue_refs("Closes #7", "o/r"), [("o/r", 7)])
        self.assertEqual(
            review.issue_refs("https://github.com/other/proj/issues/9", "o/r"),
            [("other/proj", 9)],
        )
        self.assertEqual(review.issue_refs("#5 and #5 again", "o/r"), [("o/r", 5)])


class TestResolveRequirements(unittest.TestCase):
    def pr(self, body="Implements #7", number=42):
        return {"number": number, "title": "A title", "body": body}

    def test_the_pr_body_always_leads(self):
        out = review.resolve_requirements(FakeGitHub(), "o/r", self.pr(), acc())
        self.assertIn("Implements #7", out)

    def test_a_linked_issue_body_is_appended(self):
        gh = FakeGitHub(issues={"/repos/o/r/issues/7": {"title": "Do the thing", "body": "Details here"}})
        out = review.resolve_requirements(gh, "o/r", self.pr(), acc())
        self.assertIn("Do the thing", out)
        self.assertIn("Details here", out)

    def test_human_pr_comments_are_included(self):
        gh = FakeGitHub(comments={"/repos/o/r/issues/42/comments": [
            {"user": {"login": "alice", "type": "User"}, "body": "Do not do it that way"},
        ]})
        out = review.resolve_requirements(gh, "o/r", self.pr(body="no refs"), acc())
        self.assertIn("Do not do it that way", out)
        self.assertIn("alice", out)

    def test_bot_comments_are_filtered_out(self):
        gh = FakeGitHub(comments={"/repos/o/r/issues/42/comments": [
            {"user": {"login": "renovate[bot]", "type": "Bot"}, "body": "Updated deps"},
        ]})
        out = review.resolve_requirements(gh, "o/r", self.pr(body="no refs"), acc())
        self.assertNotIn("Updated deps", out)

    def test_an_empty_body_with_no_refs_degrades_to_the_current_message(self):
        out = review.resolve_requirements(FakeGitHub(), "o/r", self.pr(body=""), acc())
        self.assertIn("none stated", out)

    def test_a_github_failure_still_returns_the_pr_body(self):
        out = review.resolve_requirements(FakeGitHub(fail=True), "o/r", self.pr(), acc())
        self.assertIn("Implements #7", out)

    def test_offline_with_no_client_returns_the_pr_body(self):
        out = review.resolve_requirements(None, "o/r", self.pr(), acc())
        self.assertIn("Implements #7", out)


class TestResolveRequirementsInteractions(unittest.TestCase):
    """Cases that combine body + issues + comments + truncation.

    Each part is well covered alone above; these check the crossings — order,
    partial failure of one GitHub call but not another, the five-issue cap
    enforced end to end rather than only inside issue_refs, and a bot sitting
    in the same comment list as a human.
    """

    def pr(self, body="Implements #7", number=42, title="A title"):
        return {"number": number, "title": title, "body": body}

    def test_body_then_issues_then_comments_appear_in_that_order(self):
        gh = FakeGitHub(
            issues={"/repos/o/r/issues/7": {"title": "Do the thing", "body": "Details here"}},
            comments={"/repos/o/r/issues/42/comments": [
                {"user": {"login": "alice", "type": "User"}, "body": "Please also do X"},
            ]},
        )
        out = review.resolve_requirements(gh, "o/r", self.pr(), acc())
        i_body = out.index("Implements #7")
        i_issue = out.index("Do the thing")
        i_comment = out.index("Please also do X")
        self.assertLess(i_body, i_issue)
        self.assertLess(i_issue, i_comment)

    def test_a_bot_alongside_a_human_in_the_same_thread_keeps_only_the_human(self):
        gh = FakeGitHub(comments={"/repos/o/r/issues/42/comments": [
            {"user": {"login": "renovate[bot]", "type": "Bot"}, "body": "Updated deps"},
            {"user": {"login": "alice", "type": "User"}, "body": "Do not do it that way"},
        ]})
        out = review.resolve_requirements(gh, "o/r", self.pr(body="no refs"), acc())
        self.assertIn("Do not do it that way", out)
        self.assertNotIn("Updated deps", out)

    def test_a_cross_repo_reference_is_fetched_from_the_other_repo_not_the_target(self):
        gh = FakeGitHub(issues={
            "/repos/other/proj/issues/9": {"title": "Upstream issue", "body": "Upstream details"},
        })
        pr = self.pr(body="See https://github.com/other/proj/issues/9")
        out = review.resolve_requirements(gh, "o/r", pr, acc())
        self.assertIn("/repos/other/proj/issues/9", gh.calls)
        self.assertNotIn("/repos/o/r/issues/9", gh.calls)
        self.assertIn("Upstream issue", out)
        self.assertIn("Upstream details", out)

    def test_a_reference_in_the_title_alone_is_still_resolved(self):
        gh = FakeGitHub(issues={"/repos/o/r/issues/9": {"title": "Titled issue", "body": "x"}})
        pr = self.pr(body="no refs here", title="Fixes #9")
        out = review.resolve_requirements(gh, "o/r", pr, acc())
        self.assertIn("Titled issue", out)

    def test_more_than_five_referenced_issues_still_fetches_only_five(self):
        body = " ".join(f"#{n}" for n in range(1, 20))
        gh = FakeGitHub()
        review.resolve_requirements(gh, "o/r", self.pr(body=body), acc())
        issue_calls = [c for c in gh.calls if "/issues/" in c and not c.endswith("/comments")]
        self.assertEqual(len(issue_calls), 5)

    def test_a_failed_comment_fetch_still_returns_body_and_issues(self):
        class PartialFailureGitHub:
            """Issues resolve fine; the comments call alone raises."""

            def __init__(self):
                self.calls = []

            def get(self, path):
                self.calls.append(path)
                if path.endswith("/comments"):
                    raise RuntimeError("comments endpoint is down")
                return {"title": "Do the thing", "body": "Details here"}

        out = review.resolve_requirements(PartialFailureGitHub(), "o/r", self.pr(), acc())
        self.assertIn("Implements #7", out)
        self.assertIn("Do the thing", out)
        self.assertIn("Details here", out)

    def test_the_combined_string_is_truncated_as_one_whole_not_part_by_part(self):
        gh = FakeGitHub(
            issues={"/repos/o/r/issues/7": {"title": "T" * 200, "body": "B" * 200}},
            comments={"/repos/o/r/issues/42/comments": [
                {"user": {"login": "alice", "type": "User"}, "body": "C" * 200},
            ]},
        )
        tiny = review.Accounting({"changed_files": 1, "call_sites": 1, "conventions": 1,
                                   "requirements": 50, "tree": 1})
        out = review.resolve_requirements(gh, "o/r", self.pr(body="B" * 200), tiny)
        self.assertLessEqual(len(out), 50)
        self.assertIn("requirements", tiny.truncated)

    def test_a_body_holding_a_code_block_is_not_cut_mid_fence(self):
        # C1: an ordinary PR body with a fenced code block in it — the most
        # reachable case of the whole defect, since the requirements string is
        # cut against its own budget by default and also reaches adjudicate().
        # An open fence quotes the diff, the lens brief and LENS_TAIL alike.
        body = "Why\n\n```python\n" + "sample_call()\n" * 400 + "```\n\nEnd.\n"
        for limit in (300, 700, 1500, 4000, 5111):
            with self.subTest(limit=limit):
                acc_ = review.Accounting({"changed_files": 1, "call_sites": 1,
                                          "conventions": 1, "requirements": limit,
                                          "tree": 1})
                out = review.resolve_requirements(None, "o/r", self.pr(body=body), acc_)
                self.assertLessEqual(len(out), limit)
                self.assertIn("requirements", acc_.truncated)
                self.assertIn("…", out)
                self.assertIsNone(unclosed_fence(out))

    def test_human_comments_section_has_no_editorial_aside(self):
        gh = FakeGitHub(comments={"/repos/o/r/issues/42/comments": [
            {"user": {"login": "alice", "type": "User"}, "body": "Do not do it that way"},
        ]})
        out = review.resolve_requirements(gh, "o/r", self.pr(body="no refs"), acc())
        self.assertIn("### Human comments on this PR", out)
        self.assertIn("Do not do it that way", out)
        self.assertNotIn("Requirements as stated by people, not by the description.", out)

    def test_a_mid_list_issue_failure_does_not_take_down_the_others(self):
        class FlakyGitHub:
            """Issue #3 (of 5 referenced) always raises; the rest resolve fine."""

            def __init__(self):
                self.calls = []

            def get(self, path):
                self.calls.append(path)
                if path.endswith("/comments"):
                    return []
                number = int(path.rsplit("/", 1)[-1])
                if number == 3:
                    raise RuntimeError("issue 3 is unreachable")
                return {"title": f"Issue {number}", "body": f"Body {number}"}

        body = " ".join(f"#{n}" for n in range(1, 6))  # #1 #2 #3 #4 #5
        out = review.resolve_requirements(FlakyGitHub(), "o/r", self.pr(body=body), acc())
        for n in (1, 2, 4, 5):
            self.assertIn(f"Issue {n}", out)
        self.assertNotIn("Issue 3", out)


if __name__ == "__main__":
    unittest.main()
