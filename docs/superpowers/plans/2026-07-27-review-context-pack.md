# Context Pack and Prompt Caching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the three lens agents the surrounding code, call sites, repo conventions and real requirements the doctrine already assumes they have, and pay for it with prompt caching on the shared prefix.

**Architecture:** A deterministic context pack is assembled in ordinary code from a tarball checkout at the PR head, then placed in a byte-identical prefix shared by all three lens calls. The lens prompt is reordered shared-first/lens-specific-last so that prefix is cacheable, and dispatch is staggered so the first lens writes the cache and the other two read it. No agentic tool loop, no new model call, no new dependency.

**Tech Stack:** Python 3.13 standard library only. GitHub REST API over `urllib`. OpenRouter chat completions with `response_format` structured outputs and `cache_control` prefix caching. Tests use stdlib `unittest`.

**Spec:** `docs/superpowers/specs/2026-07-27-review-context-pack-design.md`

## Global Constraints

Every task's requirements implicitly include this section. Values are copied verbatim from the spec.

- **Standard library only.** The deployment is a stock `python:3.13-slim` image with `review.py` and `doctrine/` mounted from a ConfigMap. There is no install step, so a new import from PyPI breaks it. This includes test code — `unittest`, not `pytest`.
- **Single file.** All new code goes in `review.py`, in a new banner section. A second module would change the ConfigMap contract in the separate `home-lab-k8s` repo.
- **`adjudicate()` keeps its exact current signature.** The enriched `requirements` string does reach it, exactly as the plain PR body does today. The other four pack parts never do — not passed, not summarised, not sampled.
- **Doctrine changes are confined to the porting note** in `doctrine/agents/pr-review-lens.md`. `doctrine/lenses/_shared.md`, the three lens briefs and `doctrine/verdict.md` stay untouched, preserving parity with the upstream `pr-reviewer` plugin in `stebennett/nyx-claude`.
- **Blocks 1 and 2 of the lens prompt must be byte-identical across the three lenses.** A single per-lens token anywhere in them destroys the cacheable prefix for all three calls.
- **`max_context_chars`** default `83000`. Per-part fractions: changed files `0.48`, call sites `0.18`, conventions `0.14`, requirements `0.13`, path tree `0.07`. Slack in an underfilled part is not reallocated.
- **Changed files:** max 25 files ordered by hunk count descending, ±60 line windows, binary sniff over the first 8KB, files over 512KB skipped outright.
- **Call sites:** names of 4+ characters, symbols with more than 40 hits dropped, max 20 symbols × 3 hits × ±8 lines.
- **`max_tarball_bytes`** default `50000000`. Extraction uses `tarfile` with `filter="data"`.
- **Linked issues:** max 5.
- **Cache:** two breakpoints. Write costs 1.25x, read 0.1x on Anthropic and DeepSeek routes.
- **Anchor violations are logged, never dropped.**
- **The pack must never fail a review.** Every failure path degrades to a smaller pack or no pack.

## Testing approach

This repo has no test suite today and `CLAUDE.md` says so. This plan adds one, because the pack is a large body of deterministic string manipulation where reading model output is a weak check. Constraints:

- `unittest` only. Run everything with:
  ```bash
  python3 -m unittest discover -s tests -t . -v
  ```
  The `-t .` sets the top-level directory to the repo root so `import review` resolves.
- **`tests/__init__.py` must exist and be empty.** With `-t .`, `unittest discover` requires the start directory to be an importable package and fails with `ImportError: Start directory is not importable` without it — verified on 3.9 and 3.14. Task 2 creates it.
- No network in any test. GitHub and OpenRouter are stubbed with hand-written fakes.
- Tests locate `doctrine/` relative to `review.__file__`, never relative to cwd.

Model-calling paths (`openrouter`, `run_lens` end to end, `adjudicate`) are **not** unit tested. They are verified by the offline A/B gates in Tasks 6 and 16, which is the method `CLAUDE.md` prescribes.

## File structure

| File | Responsibility |
|---|---|
| `review.py` | All production code. New banner section `# Context pack` between "Selection and triage" and "The pass". Modifications to `openrouter`, `run_lens`, `run_panel`, `review_pr`, `review_diff_file`, `build_parser`, `DEFAULTS`. |
| `tests/__init__.py` | Empty. Makes `tests` an importable package, which `unittest discover -t .` requires. |
| `tests/test_prompting.py` | `seg`, `completion_payload`, `strip_fence`, `build_lens_prompt` block structure and cacheability, `dispatch_lenses` ordering and concurrency. |
| `tests/test_diff.py` | `diff_paths`, `diff_anchors`, `anchor_violations`. |
| `tests/test_context.py` | `extract_checkout`, budget shares, and the four `pack_*` functions. |
| `tests/test_requirements.py` | `issue_refs` parsing and `resolve_requirements` assembly. |
| `doctrine/agents/pr-review-lens.md` | Porting note only. |
| `README.md`, `CLAUDE.md` | Docs, Task 15. |

---

### Task 1: Capture the pre-change baseline

The reorder in Task 3 changes review quality, and `--no-cache` cannot un-reorder the prompt. So the baseline must exist before any code is touched. `review.py` and `doctrine/` on this branch are currently byte-identical to `main`, so no checkout is needed — only the ordering of this task.

**Files:**
- Create: `/tmp/x.diff`, `/tmp/base.json` (deliberately outside the repo — real PR diffs are not fixtures we own)

**Interfaces:**
- Consumes: nothing
- Produces: `/tmp/x.diff` and `/tmp/base.json`, which Tasks 6 and 16 compare against. Both must survive the whole exercise; regenerating the diff later invalidates every comparison.

- [ ] **Step 1: Confirm no code has changed yet**

```bash
git diff --stat main -- review.py doctrine/
```

Expected: no output. If anything is listed, stop — the baseline is already contaminated and must be captured from `main` in a separate worktree instead.

- [ ] **Step 2: Choose a PR you know well and save its diff**

Pick a merged or open PR in a repo you understand, ideally 200-800 changed lines with more than one file, where you can personally judge whether a finding is real.

```bash
gh pr diff <PR-NUMBER> --repo <owner/repo> > /tmp/x.diff
wc -l /tmp/x.diff
```

Expected: a non-empty diff. Note the repo, because Task 16 needs a local checkout of it for `--worktree`.

- [ ] **Step 3: Capture the baseline envelopes and verdict**

```bash
python3 review.py --diff-file /tmp/x.diff --save /tmp/base.json -v
```

Expected: three lens envelopes and a verdict, and `saved envelopes + verdict to /tmp/base.json`. This costs one full review (~$0.11).

- [ ] **Step 4: Record the baseline's shape for later comparison**

```bash
python3 - <<'EOF'
import json
d = json.load(open("/tmp/base.json"))
for e in d["envelopes"]:
    blocking = sum(1 for f in e["findings"] if f["severity"] == "blocking")
    print(f'{e["lens"]:14} status={e["status"]:10} findings={len(e["findings"]):2} blocking={blocking}')
print("verdict:", d["verdict"]["verdict"], "blockers:", d["verdict"]["blocker_count"])
EOF
```

Expected: a per-lens finding count and the verdict. Paste this output into the task's completion notes — Task 6 compares against these numbers, and they are not recoverable once you have forgotten them.

- [ ] **Step 5: Commit nothing**

There is nothing to commit. `/tmp/base.json` is intentionally outside the repo.

---

### Task 2: Content-block prompts and cached-token logging

Pure plumbing. `openrouter` currently takes `system` and `user` as strings and builds the payload inline. `cache_control` markers live on message content blocks, so both must accept block arrays. No prompt content changes in this task — output should be identical to Task 1's baseline.

**Files:**
- Modify: `review.py` — new `CACHE_ENABLED` global, `seg()`, `_blocks()`, `completion_payload()`; `openrouter()` body at `review.py:364-466`
- Create: `tests/__init__.py` (empty — required by `unittest discover -t .`), `tests/test_prompting.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `CACHE_ENABLED: bool` module global, default `True`
  - `seg(text: str, *, cache: bool = False) -> dict`
  - `completion_payload(model: str, system: str | list[dict], user: str | list[dict], schema: dict, label: str) -> dict`
  - `strip_fence(text: str) -> str`
  - `openrouter(model, system, user, schema, *, label)` with `system`/`user` widened to `str | list[dict]`

**In-scope bug fix, ruled before execution.** Capturing the Task 1 baseline exposed a pre-existing bug in this exact function: a provider returned a valid JSON object wrapped in a ```` ```json ```` fence, `json.loads` rejected it, and the retry ladder paid for a whole extra generation. `provider: {"require_parameters": True}` did not prevent it — a provider can honour `response_format` and still fence its output. Since this task is already rewriting `openrouter`'s payload construction and response handling, the fix belongs here.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_prompting.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python3 -m unittest discover -s tests -t . -v
```

Expected: FAIL with `AttributeError: module 'review' has no attribute 'seg'`.

- [ ] **Step 3: Add `CACHE_ENABLED`, `seg`, `_blocks` and `completion_payload`**

In `review.py`, alongside the other module globals near `VERBOSE = False`:

```python
# Prefix caching is on by default and backed out by --no-cache or `"cache": false`.
# It is a cost optimisation only: with it off, every call is a normal uncached call.
CACHE_ENABLED = True
```

In the OpenRouter section, immediately above `openrouter()`:

```python
def seg(text: str, *, cache: bool = False) -> dict:
    """One message content block. `cache` marks a cacheable prefix ending here.

    Markers are omitted entirely when caching is disabled, rather than sent with a
    falsey value — a provider that does not understand `cache_control` should never
    see the key at all.
    """
    block = {"type": "text", "text": text}
    if cache and CACHE_ENABLED:
        block["cache_control"] = {"type": "ephemeral"}
    return block


def _blocks(content: str | list[dict]) -> list[dict]:
    return [seg(content)] if isinstance(content, str) else content


def completion_payload(
    model: str, system: str | list[dict], user: str | list[dict], schema: dict, label: str
) -> dict:
    """The request body, split out from `openrouter` so it can be tested without HTTP."""
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": _blocks(system)},
            {"role": "user", "content": _blocks(user)},
        ],
        "temperature": 0,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": label.replace("-", "_").replace(":", "_"),
                "strict": True,
                "schema": schema,
            },
        },
        # Without this, OpenRouter may route to a provider that does not support
        # response_format and SILENTLY IGNORES it — the model then returns prose,
        # json.loads fails, and the retry loop pays for another full generation
        # before failing the same way. Restrict routing to providers that honour
        # every parameter we send.
        "provider": {"require_parameters": True},
    }


def strip_fence(text: str) -> str:
    """Unwrap a markdown fence a provider wrapped its JSON object in.

    `require_parameters` is meant to route only to providers that honour
    `response_format`, and mostly it does — but a provider can honour it and
    still emit a fenced object anyway. Without this, json.loads fails and the
    retry ladder pays for an entire extra generation to fail the same way.
    Observed in the Task 1 baseline run, not defensive programming.

    Only an outermost wrapper is removed: a lens finding legitimately quotes
    fenced code inside a string value, and that must survive untouched.
    """
    t = text.strip()
    if not t.startswith("```"):
        return t
    t = t.split("\n", 1)[1] if "\n" in t else t[3:]
    if t.rstrip().endswith("```"):
        t = t.rstrip()[:-3]
    return t.strip()
```

- [ ] **Step 4: Rewrite `openrouter` to use it, and widen its signature**

Replace the inline `payload = {...}` block in `openrouter()` with:

```python
def openrouter(
    model: str,
    system: str | list[dict],
    user: str | list[dict],
    schema: dict,
    *,
    label: str,
) -> dict:
```

and inside the body:

```python
    payload = completion_payload(model, system, user, schema, label)
```

The `approx_tokens` line counts characters and must handle blocks now:

```python
    def _text(content: str | list[dict]) -> str:
        return content if isinstance(content, str) else "".join(b["text"] for b in content)

    approx_tokens = (len(_text(system)) + len(_text(user))) // 4
```

In the same function, the parse of the response content becomes fence-tolerant. Find `return json.loads(content)` and replace it with:

```python
            try:
                return json.loads(strip_fence(content))
            except json.JSONDecodeError as exc:
```

Leave the `except` block's message intact — it is still the right diagnostic for a provider that returned genuine prose rather than a fenced object.

- [ ] **Step 5: Add cached-token logging**

The spec makes this a requirement, not a diagnostic: a silent cache miss costs the 1.25x write premium for nothing, and this line is the only way to see it. Replace the existing response log in `openrouter()`:

```python
            usage = body.get("usage", {})
            details = usage.get("prompt_tokens_details") or {}
            cached = details.get("cached_tokens", 0)
            discount = body.get("cache_discount")
            heartbeat.stop()
            log(
                f"    {label}: response in {time.time() - started:.0f}s from "
                f"{body.get('provider', model)} "
                f"(in={usage.get('prompt_tokens', '?')} out={usage.get('completion_tokens', '?')} "
                f"cached={cached} discount={discount if discount is not None else '-'})"
            )
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
python3 -m unittest discover -s tests -t . -v
```

Expected: all PASS (13 tests).

- [ ] **Step 7: Verify the offline path still works and output is unchanged**

```bash
python3 review.py --diff-file /tmp/x.diff --lens craft --save /tmp/t2.json -v
```

Expected: a normal run, and the new log line showing `cached=` and `discount=`. Prompt content has not changed in this task, so the craft envelope should closely resemble Task 1's. `cached=0` here is expected and fine — no shared prefix exists yet.

- [ ] **Step 8: Commit**

```bash
git add review.py tests/test_prompting.py
git commit -m "refactor: accept content-block prompts and log cached tokens

cache_control markers live on message content blocks, so openrouter must
take arrays rather than strings. Payload construction moves into
completion_payload so it can be tested without HTTP.

Logging cached_tokens and cache_discount is a requirement rather than a
nicety: on an explicit-cache provider a silent miss costs the 1.25x write
premium for nothing, and this line is the only way to see it."
```

---

### Task 3: Reorder the lens prompt into cacheable blocks

The expensive tokens — the diff, and later the pack — are identical across the three lenses but currently sit behind a system prompt that has already diverged by lens. Reordering shared-first makes them cacheable. This is the task that changes review quality, and Task 6 gates it.

**Files:**
- Modify: `review.py` — new `LENS_TAIL` constant and `build_lens_prompt()`; `run_lens()` at `review.py:676-698`
- Modify: `tests/test_prompting.py`

**Interfaces:**
- Consumes: `seg` from Task 2
- Produces:
  - `LENS_TAIL: str`
  - `build_lens_prompt(lens: str, pr: dict, repo: str, diff: str, requirements: str, pack: str) -> tuple[list[dict], list[dict]]` returning `(system_blocks, user_blocks)`
  - `run_lens(lens, pr, repo, diff, requirements, pack, model)` — note the new `pack` parameter, positioned before `model`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_prompting.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python3 -m unittest discover -s tests -t . -v
```

Expected: FAIL with `AttributeError: module 'review' has no attribute 'build_lens_prompt'`.

- [ ] **Step 3: Add the rewritten tail instruction**

In `review.py`, immediately above `run_lens()`:

```python
# The deployment-specific tail. Doctrine stays verbatim upstream, so caveats about
# this deployment live here and in the porting note — see CLAUDE.md.
LENS_TAIL = (
    "You have no tools in this deployment. Everything you get to see is in this "
    "prompt: the diff above is your diff of record, and the context sections that "
    "follow it — changed files at head, call sites, repo conventions, the path tree — "
    "are your substitute for a worktree. Read around the diff there.\n\n"
    "Where a context section is absent, or carries a truncation marker such as "
    "`… 340 lines elided …`, that is code you have not seen. Do not speculate about "
    "it. If a finding depends on something you cannot see, either omit it or file it "
    "as advisory and say in `consequence` that it is unverified.\n\n"
    "Context informs a finding; it never locates one. Every finding must anchor to a "
    "`path:line` the diff itself touches — a line you found only by reading the "
    "context sections is not a valid anchor. Return only the JSON envelope."
)
```

- [ ] **Step 4: Add `build_lens_prompt`**

```python
def build_lens_prompt(
    lens: str, pr: dict, repo: str, diff: str, requirements: str, pack: str
) -> tuple[list[dict], list[dict]]:
    """Three blocks: shared doctrine | shared content | lens-specific tail.

    Blocks 1 and 2 are the cacheable prefix, and they MUST be byte-identical
    across the three lenses — one lens-dependent character anywhere in them and
    all three calls miss the cache. That is why the lens name and the lens brief
    are in block 3 and nowhere else, and why nothing here may be reordered for
    readability. tests/test_prompting.py enforces it.
    """
    doctrine = "\n\n".join([DOC("agents/pr-review-lens.md"), DOC("lenses/_shared.md")])
    shared = (
        f"pr: {pr['number']}\n"
        f"target_repo: {repo}\n\n"
        f"## PR title\n{pr.get('title', '')}\n\n"
        f"## PR body\n{pr.get('body') or '(empty)'}\n\n"
        f"## Resolved requirements\n{requirements}\n\n"
        f"## Prior recommendations\n{pr.get('_prior_body') or '(none — this is round 1)'}\n\n"
        f"## Diff (`gh pr diff` canonical rendering)\n```diff\n{diff}\n```\n"
    )
    if pack:
        shared += f"\n{pack}\n"
    tail = f"lens: {lens}\n\n{DOC(f'lenses/{lens}.md')}\n\n{LENS_TAIL}"
    return [seg(doctrine, cache=True)], [seg(shared, cache=True), seg(tail)]
```

- [ ] **Step 5: Rewrite `run_lens` to use it**

Replace the whole body of `run_lens`:

```python
def run_lens(
    lens: str, pr: dict, repo: str, diff: str, requirements: str, pack: str, model: str
) -> dict:
    system, user = build_lens_prompt(lens, pr, repo, diff, requirements, pack)
    return openrouter(model, system, user, LENS_SCHEMA, label=f"lens:{lens}")
```

- [ ] **Step 6: Update the two call sites to pass an empty pack**

The pack does not exist until Task 9. In `run_panel`, the `pool.submit` call becomes:

```python
            pool.submit(run_lens, lens, pr, repo, diff, requirements, "", opts.model_lens): lens
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
python3 -m unittest discover -s tests -t . -v
```

Expected: all PASS (22 tests).

- [ ] **Step 8: Verify the full offline path runs**

```bash
python3 review.py --diff-file /tmp/x.diff --lens craft -v
```

Expected: a normal craft envelope. Read it: the findings should be recognisably the same kind of thing as Task 1's craft envelope. A craft lens that has started filing correctness findings means the scope fence weakened when the brief moved out of the system prompt — note it and raise it at Task 6 rather than patching the doctrine.

- [ ] **Step 9: Commit**

```bash
git add review.py tests/test_prompting.py
git commit -m "refactor: order the lens prompt shared-first for cacheability

The diff is identical across the three lenses but sat behind a system
prompt that had already diverged by lens, so none of it was cacheable.
Reorders into shared doctrine | shared content | lens tail, with the lens
name and brief confined to the tail.

Tests assert the two cacheable blocks are byte-identical across lenses,
which is the invariant the whole caching saving rests on."
```

---

### Task 4: Staggered dispatch

Three lenses dispatched in parallel all miss a cold cache and all three *write* it at 1.25x — strictly worse than not caching. Sequencing the first turns the other two into reads.

**Files:**
- Modify: `review.py` — new `dispatch_lenses()`; `run_panel()` at `review.py:765-815`
- Modify: `tests/test_prompting.py`

**Interfaces:**
- Consumes: `run_lens` from Task 3
- Produces: `dispatch_lenses(lenses: tuple[str, ...], runner: Callable[[str], dict], *, stagger: bool) -> list[dict]` returning envelopes in `lenses` order

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_prompting.py` (add `import threading` and `import time` to the imports at the top):

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python3 -m unittest discover -s tests -t . -v
```

Expected: FAIL with `AttributeError: module 'review' has no attribute 'dispatch_lenses'`.

- [ ] **Step 3: Add `dispatch_lenses`**

Above `run_panel()`:

```python
def dispatch_lenses(lenses: tuple[str, ...], runner, *, stagger: bool) -> list[dict]:
    """Run every lens, returning envelopes in `lenses` order.

    With `stagger`, the first lens runs alone so that it writes the shared cache
    prefix, and the rest then read it. Three cold parallel calls would each pay
    the cache-write premium and none would read — worse than not caching at all.
    The cost is wall clock: one lens-latency becomes two.

    `runner` must not raise for a merely-failed lens; run_panel wraps it so a
    failure becomes a needs-input envelope instead of losing the whole panel.
    """
    head: tuple[str, ...] = ()
    tail = lenses
    if stagger and len(lenses) > 1:
        head, tail = lenses[:1], lenses[1:]

    results = {lens: runner(lens) for lens in head}

    if tail:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(tail)) as pool:
            futures = {pool.submit(runner, lens): lens for lens in tail}
            for fut in concurrent.futures.as_completed(futures):
                results[futures[fut]] = fut.result()

    return [results[lens] for lens in lenses]
```

- [ ] **Step 4: Rewrite `run_panel`'s dispatch to use it**

Replace the `with concurrent.futures.ThreadPoolExecutor(...)` block in `run_panel` with:

```python
    def runner(lens: str) -> dict:
        # A failed lens must not lose the other two, so the envelope is
        # synthesised here rather than allowed to escape dispatch_lenses.
        try:
            return run_lens(lens, pr, repo, diff, requirements, "", opts.model_lens)
        except Exception as exc:  # noqa: BLE001
            log(f"    lens:{lens} FAILED: {exc}")
            return {"lens": lens, "status": "needs-input", "findings": [], "notes": f"failed: {exc}"}

    stagger = CACHE_ENABLED and len(lenses) > 1
    if stagger:
        log(f"  staggering: {lenses[0]} first to write the cache, then {len(lenses) - 1} in parallel")
    envelopes = dispatch_lenses(lenses, runner, stagger=stagger)
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
python3 -m unittest discover -s tests -t . -v
```

Expected: all PASS (28 tests).

- [ ] **Step 6: Verify staggering on a real run and read the cache numbers**

```bash
python3 review.py --diff-file /tmp/x.diff --save /tmp/t4.json -v
```

Expected: the `staggering:` line, then `lens:requirements` alone, then the other two together. Read the `cached=` value on lenses 2 and 3. Non-zero means caching works on this route. Zero is the outcome Task 6 has to decide about — record the numbers, do not act on them yet.

- [ ] **Step 7: Commit**

```bash
git add review.py tests/test_prompting.py
git commit -m "feat: stagger lens dispatch so the first call writes the cache

Three cold parallel calls would each pay the 1.25x cache-write premium
and none would read, which is worse than not caching. Running the first
lens alone turns the other two into 0.1x reads, at the cost of one extra
lens-latency of wall clock.

Per-lens failure handling moves into a runner closure so dispatch_lenses
stays a plain scheduling primitive and a failed lens still cannot take
the panel down with it."
```

---

### Task 5: `--no-cache` and the `cache` config key

Caching must be backable-out without editing code: the spec requires it as the escape hatch when a route does not honour `cache_control`, and Task 6 may well need it.

**Files:**
- Modify: `review.py` — `DEFAULTS` at `review.py:73-81`, `build_parser()`, `main()`, `review_pr()`, `review_diff_file()`

**Interfaces:**
- Consumes: `CACHE_ENABLED` from Task 2
- Produces: `--no-cache` CLI flag; `cache` config key; `resolve_cache(opts, cfg) -> bool`

- [ ] **Step 1: Add the config default**

In `DEFAULTS`:

```python
    "cache": True,
```

- [ ] **Step 2: Add the CLI flag**

In `build_parser()`, next to `--post`:

```python
    p.add_argument("--no-cache", action="store_true",
                   help="disable prompt caching and revert to a single parallel lens wave")
```

- [ ] **Step 3: Add the resolver and wire it in**

Next to `resolve_post()`:

```python
def resolve_cache(opts: argparse.Namespace, cfg: dict | None = None) -> bool:
    """Caching is on unless the CLI or the target repo's config turns it off.

    The CLI wins, so --no-cache is always an effective escape hatch regardless of
    what a target repo asks for.
    """
    if opts.no_cache:
        return False
    return bool((cfg or DEFAULTS).get("cache", True))
```

In `review_pr()`, before `run_panel` is called, and in `review_diff_file()` before its `run_panel` call:

```python
    global CACHE_ENABLED
    CACHE_ENABLED = resolve_cache(opts, cfg)
```

`review_diff_file` has no repo config, so it passes `None`:

```python
    global CACHE_ENABLED
    CACHE_ENABLED = resolve_cache(opts)
```

- [ ] **Step 4: Verify both settings take effect**

```bash
python3 review.py --diff-file /tmp/x.diff --lens craft --no-cache -v 2>&1 | grep -E "staggering|cached="
```

Expected: no `staggering:` line (a single lens never staggers anyway), and `cached=0`.

```bash
python3 review.py --diff-file /tmp/x.diff --no-cache -v 2>&1 | grep -E "staggering|cached="
```

Expected: no `staggering:` line, three lenses dispatched at once, `cached=0` on all three.

- [ ] **Step 5: Commit**

```bash
git add review.py
git commit -m "feat: add --no-cache and the cache config key

The spec requires caching to be backable-out without a code edit, because
whether a given OpenRouter route honours cache_control has to be measured
rather than assumed. The CLI flag wins over repo config so it stays an
effective escape hatch."
```

---

### Task 6: Gate 1 — verify the reorder and caching

A verification gate, not a code change. It answers two independent questions: did moving the lens brief cost review quality, and does caching actually work on this route. Both must be answered before the pack is built on top and confounds them.

**Files:**
- Reads: `/tmp/base.json` from Task 1
- Create: `/tmp/reordered.json`

**Interfaces:**
- Consumes: everything from Tasks 2-5
- Produces: a go/no-go decision, and possibly `cache: false` in `DEFAULTS`

- [ ] **Step 1: Run the reordered, cached panel over the same diff**

```bash
python3 review.py --diff-file /tmp/x.diff --save /tmp/reordered.json -v 2>&1 | tee /tmp/reordered.log
```

Do not regenerate `/tmp/x.diff` — a different diff invalidates the comparison.

- [ ] **Step 2: Compare the finding shape against the baseline**

```bash
python3 - <<'EOF'
import json
for name in ("base", "reordered"):
    d = json.load(open(f"/tmp/{name}.json"))
    print(f"--- {name}")
    for e in sorted(d["envelopes"], key=lambda e: e["lens"]):
        blocking = sum(1 for f in e["findings"] if f["severity"] == "blocking")
        print(f'  {e["lens"]:14} status={e["status"]:10} findings={len(e["findings"]):2} blocking={blocking}')
        for f in e["findings"]:
            print(f'      [{f["severity"]:8}] {f["path"]}:{f["line"]} {f["claim"][:70]}')
    print("  verdict:", d["verdict"]["verdict"], d["verdict"]["blocker_count"])
EOF
```

Read for:

1. **Do the same blocking findings survive?** Not identical text — temperature 0 does not make output stable across a changed prompt — but a blocking finding that was real in the baseline and has vanished is a regression.
2. **Has any lens started wandering outside its lens?** A craft lens filing correctness findings, or a requirements lens filing style notes, means the scope fence weakened when the brief moved out of the system prompt.

If either fails, **stop and reconsider the reorder** rather than patching the doctrine to compensate. Falling back to Tier 1 only — leaving the shared doctrine cached in the system prompt and reverting Task 3 — keeps ~5% of the saving with none of the risk.

- [ ] **Step 3: Confirm the cache is actually being read**

```bash
grep -E "lens:(requirements|correctness|craft):.*cached=" /tmp/reordered.log
```

Expected: `cached=0` on `lens:requirements` (it writes), and a large non-zero `cached=` on the other two.

- [ ] **Step 4: Decide on caching, and record the numbers**

- **Non-zero reads on lenses 2 and 3** → caching works. Keep it. Record the `cached=` and `discount=` values in the task notes.
- **Zero on all three** → this route ignores `cache_control`. Set `"cache": False` in `DEFAULTS`, commit that with the measured evidence in the message, and leave the machinery in place for a future model change. Do not ship staggered dispatch without cache reads — it buys latency for nothing.
- **Routing errors or a provider refusal** → check the `provider: {"require_parameters": True}` interaction flagged in the spec. Try one run with that key removed to see whether it is the cause, then restore it: it is load-bearing for `response_format` and must not be dropped as a fix.

- [ ] **Step 5: Commit any decision that changed code**

```bash
# only if Step 4 concluded caching does not work on this route
git add review.py
git commit -m "chore: default cache off — <model> route ignores cache_control

Measured on <date>: lenses 2 and 3 reported cached=0 across a full panel,
so the 1.25x write premium was being paid with no reads. Machinery stays
in place behind the cache key for a future model change."
```

---

### Task 7: Diff parsing

Two pure functions the pack and the anchor validator both need. No model, no network, no filesystem.

**Files:**
- Modify: `review.py` — new `# Context pack` banner section between "Selection and triage" and "The pass"
- Create: `tests/test_diff.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `diff_paths(diff: str) -> dict[str, list[tuple[int, int]]]` — path to RIGHT-side `(start, end)` inclusive ranges the diff touches
  - `diff_anchors(diff: str) -> set[tuple[str, int, str]]` — `(path, line, side)` triples GitHub will accept as a comment anchor

- [ ] **Step 1: Write the failing tests**

Create `tests/test_diff.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python3 -m unittest discover -s tests -t . -v
```

Expected: FAIL with `AttributeError: module 'review' has no attribute 'diff_paths'`.

- [ ] **Step 3: Add the banner section and the two parsers**

Insert into `review.py` between the "Selection and triage" and "The pass" sections:

```python
# ─────────────────────────────────────────────────────────────────────────────
# Context pack
#
# The lens doctrine (doctrine/lenses/_shared.md, ## Method) tells a lens to read
# around the diff for "context the hunk alone hides". Upstream that was a worktree
# plus Read/Grep/Glob; here it is this section, which pushes the same information
# into the prompt deterministically. No model call is involved in any of it.
# ─────────────────────────────────────────────────────────────────────────────

HUNK_RE = re.compile(r"^@@ -(?P<old>\d+)(?:,(?P<oldc>\d+))? \+(?P<new>\d+)(?:,(?P<newc>\d+))? @@")


def _strip_prefix(target: str) -> str | None:
    """`a/src/foo.py` -> `src/foo.py`; `/dev/null` -> None."""
    if target == "/dev/null":
        return None
    return target[2:] if target[:2] in ("a/", "b/") else target


def _hunks(diff: str) -> list[tuple[str | None, str | None, int, int, list[str]]]:
    """One (new_path, old_path, old_start, new_start, body) tuple per hunk.

    Both paths are tracked, not just the `+++` one: a deleted file has
    `+++ /dev/null` and no RIGHT side, but GitHub still accepts a LEFT comment on
    it, so its `--- a/path` is the only way to anchor there.
    """
    out: list[tuple[str | None, str | None, int, int, list[str]]] = []
    new_path: str | None = None
    old_path: str | None = None
    header: re.Match | None = None
    body: list[str] = []

    def close() -> None:
        if header is not None:
            out.append(
                (new_path, old_path, int(header.group("old")), int(header.group("new")), list(body))
            )

    for line in diff.splitlines():
        if line.startswith(("diff --git ", "index ")):
            continue
        if line.startswith("--- "):
            # The `---` line opens a new file, so it also closes the previous
            # file's last hunk — while old_path/new_path still name that file.
            close()
            header, body = None, []
            old_path = _strip_prefix(line[4:].strip())
            continue
        if line.startswith("+++ "):
            new_path = _strip_prefix(line[4:].strip())
            continue
        m = HUNK_RE.match(line)
        if m:
            close()
            header, body = m, []
            continue
        if header is not None:
            body.append(line)
    close()
    return out


def diff_paths(diff: str) -> dict[str, list[tuple[int, int]]]:
    """path -> RIGHT-side (start, end) inclusive line ranges the diff touches.

    Deleted files are absent: there is no head-side file to read for them.
    """
    out: dict[str, list[tuple[int, int]]] = {}
    for new_path, _old_path, _old, new, body in _hunks(diff):
        if new_path is None:
            continue
        span = sum(1 for ln in body if not ln.startswith("-"))
        if span:
            out.setdefault(new_path, []).append((new, new + span - 1))
    return out


def diff_anchors(diff: str) -> set[tuple[str, int, str]]:
    """(path, line, side) triples GitHub will accept as an inline comment anchor.

    A comment on a line the diff does not touch makes GitHub reject the ENTIRE
    review with a 422, which is why this exists — see post_review's fallback.
    """
    anchors: set[tuple[str, int, str]] = set()
    for new_path, old_path, old, new, body in _hunks(diff):
        old_n, new_n = old, new
        for line in body:
            if line.startswith("+"):
                if new_path:
                    anchors.add((new_path, new_n, "RIGHT"))
                new_n += 1
            elif line.startswith("-"):
                if old_path:
                    anchors.add((old_path, old_n, "LEFT"))
                old_n += 1
            else:
                if new_path:
                    anchors.add((new_path, new_n, "RIGHT"))
                if old_path:
                    anchors.add((old_path, old_n, "LEFT"))
                old_n += 1
                new_n += 1
    return anchors
```

Note: `_hunks` uses `yield from flush()` where `flush` is itself a generator, so the final hunk is emitted after the loop ends.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python3 -m unittest discover -s tests -t . -v
```

Expected: all PASS (39 tests). If `test_right_side_ranges_cover_the_hunk` fails, check that removed lines are excluded from the span — a `-` line consumes no RIGHT-side line number.

- [ ] **Step 5: Sanity-check against the real diff**

```bash
python3 -c "
import review, pathlib
d = pathlib.Path('/tmp/x.diff').read_text()
paths = review.diff_paths(d)
print(f'{len(paths)} files, {sum(len(v) for v in paths.values())} hunks, {len(review.diff_anchors(d))} anchors')
for p, r in list(paths.items())[:5]: print(' ', p, r)
"
```

Expected: a file count matching what `gh pr diff` shows, and a plausible anchor count. A file count of zero means the header parsing is wrong for this diff's format.

- [ ] **Step 6: Commit**

```bash
git add review.py tests/test_diff.py
git commit -m "feat: parse diff paths and comment anchors

Two pure functions the pack and the anchor validator both need. Anchors
matter because a comment on an untouched line makes GitHub reject the
entire review with a 422."
```

---

### Task 8: Anchor validation

The pack's characteristic new failure mode is a lens citing a line it found by browsing rather than in the diff. Landing the validator *before* the pack means Task 16 has a known-zero baseline to compare against.

**Files:**
- Modify: `review.py` — new `anchor_violations()`; `run_panel()`
- Modify: `tests/test_diff.py`

**Interfaces:**
- Consumes: `diff_anchors` from Task 7
- Produces: `anchor_violations(envelopes: list[dict], diff: str) -> list[tuple[str, dict]]` returning `(lens, finding)` pairs

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_diff.py`:

```python
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
        env = [self.envelope("craft", [_finding("src/bar.py", 900)])]
        self.assertEqual(len(review.anchor_violations(env, TWO_FILES)), 1)

    def test_a_finding_on_an_untouched_file_is_a_violation(self):
        env = [self.envelope("craft", [_finding("src/elsewhere.py", 1)])]
        self.assertEqual(len(review.anchor_violations(env, TWO_FILES)), 1)

    def test_the_side_is_part_of_the_anchor_key(self):
        # bar.py has three RIGHT lines but only two LEFT ones, so RIGHT 3 is a
        # valid anchor and LEFT 3 is not.
        anchors = review.diff_anchors(TWO_FILES)
        self.assertIn(("src/bar.py", 3, "RIGHT"), anchors)
        env = [self.envelope("craft", [_finding("src/bar.py", 3, side="LEFT")])]
        self.assertEqual(len(review.anchor_violations(env, TWO_FILES)), 1)

    def test_the_offending_lens_is_reported_with_the_finding(self):
        env = [self.envelope("correctness", [_finding("nope.py", 1)])]
        lens, finding = review.anchor_violations(env, TWO_FILES)[0]
        self.assertEqual(lens, "correctness")
        self.assertEqual(finding["path"], "nope.py")

    def test_a_needs_input_envelope_with_no_findings_is_fine(self):
        env = [{"lens": "craft", "status": "needs-input", "findings": [], "notes": "failed"}]
        self.assertEqual(review.anchor_violations(env, TWO_FILES), [])
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python3 -m unittest discover -s tests -t . -v
```

Expected: FAIL with `AttributeError: module 'review' has no attribute 'anchor_violations'`.

- [ ] **Step 3: Add `anchor_violations`**

In the "Context pack" section, after `diff_anchors`:

```python
def anchor_violations(envelopes: list[dict], diff: str) -> list[tuple[str, dict]]:
    """Findings anchored outside the diff, as (lens, finding) pairs.

    Doctrine etiquette rule 4 forbids these, and giving a lens surrounding code
    makes them tempting. They are REPORTED, never dropped: a real bug cited at a
    slightly wrong line is worth more than a clean log, and post_review already
    folds inline comments into the body when GitHub rejects them with a 422.
    The count is the signal for whether the pack is eroding lens discipline.
    """
    anchors = diff_anchors(diff)
    return [
        (env["lens"], f)
        for env in envelopes
        for f in env.get("findings") or []
        if (f["path"], f["line"], f["side"]) not in anchors
    ]
```

- [ ] **Step 4: Report violations in `run_panel`**

After the envelopes are collected and before adjudication:

```python
    violations = anchor_violations(envelopes, diff)
    if violations:
        log(f"  WARNING: {len(violations)} finding(s) anchored outside the diff (kept, not dropped):")
        for lens, f in violations:
            log(f"    lens:{lens} {f['path']}:{f['line']} {f['side']} — {f['claim'][:80]}")
    else:
        log("  anchors: all findings anchor inside the diff")
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
python3 -m unittest discover -s tests -t . -v
```

Expected: all PASS (45 tests).

- [ ] **Step 6: Establish the pre-pack violation baseline**

```bash
python3 review.py --diff-file /tmp/x.diff -v 2>&1 | grep -E "anchors:|anchored outside"
```

Expected: ideally `anchors: all findings anchor inside the diff`. Record whatever it says — a non-zero count here is pre-existing and is the number Task 16 must not exceed.

- [ ] **Step 7: Commit**

```bash
git add review.py tests/test_diff.py
git commit -m "feat: report findings anchored outside the diff

Doctrine etiquette rule 4 already forbids these; a lens with surrounding
code will be tempted. Reported and kept rather than dropped, because a
real bug at a slightly wrong line beats a clean log and post_review
already handles GitHub's 422. Landed before the pack so there is a
known baseline to compare against."
```

---

### Task 9: Pack framework — checkout, budgets, accounting

Everything the pack needs except the parts themselves. Ends with an empty-but-wired pack, so the plumbing is verified before any content depends on it.

**Files:**
- Modify: `review.py` — `DEFAULTS`; `GitHub.file()`; new `Context`, `build_context`, `fetch_checkout`, `stream_capped`, `extract_checkout`, `CONTEXT_SHARES`, `budgets`, `Accounting`; `review_pr()`, `review_diff_file()`, `run_panel()`, `run_lens` call, `build_parser()`
- Create: `tests/test_context.py`

**Interfaces:**
- Consumes: `diff_paths` from Task 7
- Produces:
  - `CONTEXT_SHARES: dict[str, float]`
  - `budgets(total: int) -> dict[str, int]`
  - `class Accounting` with `.add(part: str, text: str) -> str` and `.report() -> None`
  - `stream_capped(response, dest: Path, cap: int) -> bool`
  - `extract_checkout(archive: Path, dest: Path) -> Path | None`
  - `fetch_checkout(gh: GitHub, repo: str, sha: str, dest: Path, cap: int) -> Path | None`
  - `class Context` with `.pack: str`, `.requirements: str`, `.notes: list[str]`, `.root: Path | None`
  - `build_context(gh, repo, pr, diff, cfg, *, enabled, worktree=None)` as a context manager
  - `--no-context`, `--worktree PATH` CLI flags; `context`, `max_context_chars`, `max_tarball_bytes` config keys

- [ ] **Step 1: Write the failing tests**

Create `tests/test_context.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python3 -m unittest discover -s tests -t . -v
```

Expected: FAIL with `AttributeError: module 'review' has no attribute 'CONTEXT_SHARES'`.

- [ ] **Step 3: Add the config keys and widen `GitHub.file`**

In `DEFAULTS`:

```python
    "context": True,
    "max_context_chars": 83000,
    "max_tarball_bytes": 50_000_000,
```

`GitHub.file()` needs a `ref` so degraded fetches read the PR head rather than the default branch, and a raw-bytes fetch for the tarball:

```python
    def file(self, repo: str, path: str, ref: str | None = None) -> str | None:
        """Fetch a file's contents, or None if it does not exist."""
        h = dict(self._h, Accept="application/vnd.github.v3.raw")
        url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
        if ref:
            url += f"?ref={ref}"
        try:
            return _http("GET", url, headers=h, raw=True)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def open_tarball(self, repo: str, sha: str):
        """An open response streaming the repo tarball at `sha`."""
        req = urllib.request.Request(
            f"{GITHUB_API}/repos/{repo}/tarball/{sha}", method="GET", headers=self._h
        )
        return urllib.request.urlopen(req, timeout=180)
```

- [ ] **Step 4: Add budgets and accounting**

In the "Context pack" section:

```python
# Fractions of max_context_chars, not absolute sizes, so one config knob scales the
# whole pack. Must sum to 1.0 — tests/test_context.py asserts it. Slack in an
# underfilled part is deliberately NOT reallocated: that is a tuning-time
# optimisation with no evidence behind it yet.
CONTEXT_SHARES = {
    "changed_files": 0.48,
    "call_sites": 0.18,
    "conventions": 0.14,
    "requirements": 0.13,
    "tree": 0.07,
}


def budgets(total: int) -> dict[str, int]:
    return {part: int(total * share) for part, share in CONTEXT_SHARES.items()}


class Accounting:
    """Enforces per-part budgets and records what each part actually used.

    Truncation is always marked in-band: a lens that cannot tell a truncated
    section from a complete one will treat absence as evidence, which is exactly
    the failure the porting note warns about.
    """

    def __init__(self, limits: dict[str, int]) -> None:
        self.limits = limits
        self.used = {part: 0 for part in limits}
        self.truncated: set[str] = set()

    def add(self, part: str, text: str) -> str:
        limit = self.limits[part]
        if len(text) > limit:
            self.truncated.add(part)
            marker = f"\n\n… truncated: {part} exceeded its {limit}-character budget …\n"
            text = text[: max(0, limit - len(marker))] + marker
        self.used[part] = len(text)
        return text

    def report(self) -> None:
        for part, limit in self.limits.items():
            used = self.used[part]
            flag = " TRUNCATED" if part in self.truncated else ""
            state = "empty" if used == 0 else f"{used}/{limit} chars"
            log(f"    context {part}: {state}{flag}")
```

- [ ] **Step 5: Add checkout acquisition**

```python
def stream_capped(response, dest: Path, cap: int) -> bool:
    """Stream `response` to `dest`, aborting past `cap` bytes. True if complete.

    The tarball size is not known before the download starts, so the cap is
    enforced as it arrives. On abort the partial file is removed — a truncated
    archive is worse than none, because it extracts a plausible-looking subset.
    """
    written = 0
    try:
        with dest.open("wb") as fh:
            while True:
                chunk = response.read(65536)
                if not chunk:
                    return True
                written += len(chunk)
                if written > cap:
                    fh.close()
                    dest.unlink(missing_ok=True)
                    return False
                fh.write(chunk)
    except Exception:  # noqa: BLE001 - a failed download degrades the pack, never the review
        dest.unlink(missing_ok=True)
        return False


def extract_checkout(archive: Path, dest: Path) -> Path | None:
    """Extract a GitHub tarball and return its single top-level directory.

    `filter="data"` is what refuses absolute paths, traversal entries, symlinks
    out of the tree and device files. It is stdlib from 3.12, which is why no
    dependency is needed here.
    """
    try:
        dest.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(dest, filter="data")
    except Exception as exc:  # noqa: BLE001
        vlog(f"    context: could not extract {archive.name}: {exc}")
        return None
    tops = [p for p in dest.iterdir() if p.is_dir()]
    return tops[0] if len(tops) == 1 else dest


def fetch_checkout(gh: GitHub, repo: str, sha: str, dest: Path, cap: int) -> Path | None:
    """A read-only checkout at `sha`, or None if it could not be obtained."""
    archive = dest / "src.tar.gz"
    try:
        with gh.open_tarball(repo, sha) as resp:
            if not stream_capped(resp, archive, cap):
                log(f"  context: tarball for {repo}@{sha[:7]} exceeded {cap} bytes; degrading")
                return None
    except Exception as exc:  # noqa: BLE001
        log(f"  context: could not fetch tarball for {repo}@{sha[:7]} ({exc}); degrading")
        return None
    return extract_checkout(archive, dest / "tree")
```

Add `import tarfile` and `from contextlib import contextmanager` to the imports.

- [ ] **Step 6: Add `Context` and `build_context`, producing an empty pack for now**

```python
class Context:
    """What the lenses get beyond the diff. `pack` is "" when there is nothing."""

    def __init__(self, requirements: str) -> None:
        self.pack = ""
        self.requirements = requirements
        self.notes: list[str] = []
        self.root: Path | None = None


@contextmanager
def build_context(
    gh: GitHub | None,
    repo: str,
    pr: dict,
    diff: str,
    cfg: dict,
    *,
    enabled: bool,
    worktree: str | None = None,
):
    """Assemble the pack, owning the temp checkout for exactly one PR.

    Never raises on a pack failure: a review with a thin pack is worth far more
    than no review, so every path here degrades and records why in `notes`.
    """
    ctx = Context(pr.get("body") or "(none stated — judge against the PR title alone)")
    if not enabled:
        ctx.notes.append("context disabled")
        yield ctx
        return

    tmp: tempfile.TemporaryDirectory | None = None
    try:
        if worktree:
            root = Path(worktree).expanduser().resolve()
            ctx.root = root if root.is_dir() else None
            if ctx.root is None:
                ctx.notes.append(f"--worktree {worktree} is not a directory")
        elif gh is not None:
            tmp = tempfile.TemporaryDirectory(prefix="pr-reviewer-")
            head_repo = ((pr.get("head") or {}).get("repo") or {}).get("full_name") or repo
            ctx.root = fetch_checkout(
                gh, head_repo, pr["head"]["sha"], Path(tmp.name), cfg["max_tarball_bytes"]
            )
            if ctx.root is None:
                ctx.notes.append("no checkout; changed files fetched per-file")
        else:
            ctx.notes.append("no checkout available (offline without --worktree)")

        acc = Accounting(budgets(cfg["max_context_chars"]))
        # Parts are filled in Tasks 10-13.
        acc.report()
        for note in ctx.notes:
            log(f"    context note: {note}")
        yield ctx
    finally:
        if tmp is not None:
            tmp.cleanup()
```

- [ ] **Step 7: Wire it into both review paths**

In `review_pr()`, replace the `requirements = ...` line and the `run_panel` call:

```python
    with build_context(
        gh, repo, pr, diff, cfg,
        enabled=cfg.get("context", True) and not opts.no_context,
        worktree=opts.worktree,
    ) as ctx:
        verdict = run_panel(pr, repo, diff, ctx, opts)
```

In `review_diff_file()`:

```python
    cfg = dict(DEFAULTS)
    with build_context(
        None, opts.repo_name or "local/local", pr, diff, cfg,
        enabled=not opts.no_context,
        worktree=opts.worktree,
    ) as ctx:
        verdict = run_panel(pr, opts.repo_name or "local/local", diff, ctx, opts)
```

`run_panel` takes the `Context` rather than a bare `requirements` string:

```python
def run_panel(pr: dict, repo: str, diff: str, ctx: Context, opts: argparse.Namespace) -> dict | None:
```

and inside it:

```python
            return run_lens(lens, pr, repo, diff, ctx.requirements, ctx.pack, opts.model_lens)
```

```python
    # The adjudicator sees the lens envelopes, the PR body, the prior review and the
    # resolved requirements — never the diff, and never ctx.pack. That is structural:
    # doctrine/agents/pr-review-verdict.md explains why. Do not "fix" this.
    verdict = adjudicate(pr, repo, envelopes, ctx.requirements, opts.model_verdict)
```

And `--save` records the pack:

```python
                {"repo": repo, "pr": pr["number"], "pack": ctx.pack,
                 "requirements": ctx.requirements, "envelopes": envelopes, "verdict": verdict},
```

- [ ] **Step 8: Add the CLI flags**

In `build_parser()`:

```python
    p.add_argument("--no-context", action="store_true",
                   help="disable the context pack (review from the diff alone)")
    p.add_argument("--worktree", metavar="PATH",
                   help="read context from a local checkout instead of fetching a tarball")
```

- [ ] **Step 9: Run the tests to verify they pass**

```bash
python3 -m unittest discover -s tests -t . -v
```

Expected: all PASS (58 tests — the count is indicative, the pass is not).

- [ ] **Step 10: Verify the plumbing end to end**

```bash
python3 review.py --diff-file /tmp/x.diff --lens craft --worktree ~/Code/<thatrepo> -v 2>&1 | grep -E "context "
```

Expected: five `context <part>: empty` lines and no crash. The pack has no content yet, so the review should match Task 6's.

```bash
python3 review.py --diff-file /tmp/x.diff --lens craft --worktree /nonexistent -v 2>&1 | grep -E "context note"
```

Expected: `context note: --worktree /nonexistent is not a directory`, and the review still completes.

- [ ] **Step 11: Commit**

```bash
git add review.py tests/test_context.py
git commit -m "feat: add the context pack framework

Tarball checkout at the PR head via stdlib tarfile with filter=data, so
no git binary and no dependency. Budgets are fractions of one
max_context_chars knob; Accounting marks truncation in-band because a
lens that cannot see a section was cut will treat absence as evidence.

Every failure path degrades rather than failing the review. Parts are
empty until the next four tasks."
```

---

### Task 10: Pack part — changed files at head

**Files:**
- Modify: `review.py` — new `path_matches`, `is_binary`, `read_source`, `merge_ranges`, `windowed`, `pack_changed_files`; `build_context()`
- Modify: `tests/test_context.py`

**Interfaces:**
- Consumes: `Accounting`, `diff_paths`, `Context.root`
- Produces:
  - `path_matches(path: str, patterns: list[str]) -> bool`
  - `is_binary(data: bytes) -> bool`
  - `merge_ranges(ranges: list[tuple[int, int]], pad: int) -> list[tuple[int, int]]`
  - `windowed(text: str, ranges: list[tuple[int, int]]) -> str`
  - `pack_changed_files(root: Path | None, gh, repo, sha, ranges: dict, cfg: dict, acc: Accounting) -> str`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_context.py`:

```python
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
        self.assertIn("5 further changed file(s) not shown", out)

    def test_files_with_more_hunks_are_preferred(self):
        make_tree(self.root, {"busy.py": "b\n", "quiet.py": "q\n"})
        ranges = {"quiet.py": [(1, 1)], "busy.py": [(1, 1), (5, 6), (9, 10)]}
        cfg = dict(self.cfg, max_context_files=1)
        out = review.pack_changed_files(self.root, None, "o/r", "sha", ranges, cfg, self.acc())
        self.assertIn("b\n", out)                                   # busy.py's contents
        self.assertNotIn("q\n", out)                                # quiet.py's contents
        self.assertIn("1 further changed file(s) not shown", out)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python3 -m unittest discover -s tests -t . -v
```

Expected: FAIL with `AttributeError: module 'review' has no attribute 'path_matches'`.

- [ ] **Step 3: Add the helpers**

In the "Context pack" section:

```python
MAX_SOURCE_BYTES = 512 * 1024  # above this a file is generated or vendored, not reviewable
BINARY_SNIFF_BYTES = 8 * 1024
WINDOW_PAD = 60


def path_matches(path: str, patterns: list[str]) -> bool:
    """True if `path` matches any glob in `patterns`.

    `ignore_paths` has been in DEFAULTS since the first commit and read nowhere;
    this is its first consumer. Patterns are matched against the full path and
    against the bare filename, so both `*.lock` and `**/generated/**` behave the
    way someone writing that config would expect.
    """
    name = path.rsplit("/", 1)[-1]
    for pat in patterns:
        if fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(name, pat):
            return True
        # `**/x/**` is the conventional way to write "any directory named x",
        # which fnmatch has no special handling for.
        if pat.startswith("**/") and pat.endswith("/**") and f"/{pat.strip('*/')}/" in f"/{path}":
            return True
    return False


def is_binary(data: bytes) -> bool:
    return b"\x00" in data[:BINARY_SNIFF_BYTES]


def merge_ranges(ranges: list[tuple[int, int]], pad: int) -> list[tuple[int, int]]:
    """Pad each range by `pad` lines and merge those that now overlap."""
    padded = sorted((max(1, lo - pad), hi + pad) for lo, hi in ranges)
    out: list[tuple[int, int]] = []
    for lo, hi in padded:
        if out and lo <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def windowed(text: str, ranges: list[tuple[int, int]]) -> str:
    """Render only `ranges` of `text`, line-numbered, with elisions marked.

    Line numbers matter: without them a lens cannot relate what it reads here to
    the diff's line numbers. Elisions are stated explicitly so unseen code is
    visibly unseen rather than silently absent.
    """
    lines = text.splitlines()
    chunks: list[str] = []
    cursor = 1
    for lo, hi in ranges:
        lo, hi = max(1, lo), min(len(lines), hi)
        if lo > cursor:
            chunks.append(f"… {lo - cursor} lines elided …")
        chunks.extend(f"{n}: {lines[n - 1]}" for n in range(lo, hi + 1))
        cursor = hi + 1
    if cursor <= len(lines):
        chunks.append(f"… {len(lines) - cursor + 1} lines elided …")
    return "\n".join(chunks)
```

Add `import fnmatch` to the imports.

- [ ] **Step 4: Add `read_source` and `pack_changed_files`**

```python
def read_source(root: Path | None, gh, repo: str, sha: str, rel: str) -> str | None:
    """A changed file's text at head, from the checkout or the degraded API path."""
    if root is not None:
        p = root / rel
        try:
            if not p.is_file() or p.stat().st_size > MAX_SOURCE_BYTES:
                return None
            data = p.read_bytes()
        except OSError:
            return None
        return None if is_binary(data) else data.decode("utf-8", "replace")
    if gh is None:
        return None
    try:
        text = gh.file(repo, rel, ref=sha)
    except Exception:  # noqa: BLE001 - a file we cannot read degrades the pack only
        return None
    if text is None or len(text.encode()) > MAX_SOURCE_BYTES or is_binary(text.encode()[:BINARY_SNIFF_BYTES]):
        return None
    return text


def pack_changed_files(
    root: Path | None, gh, repo: str, sha: str,
    ranges: dict[str, list[tuple[int, int]]], cfg: dict, acc: Accounting,
) -> str:
    """Every changed file at head, whole where it fits and windowed where it does not."""
    limit = cfg.get("max_context_files", 25)
    ignore = cfg.get("ignore_paths") or []
    ordered = sorted(ranges, key=lambda p: (-len(ranges[p]), p))
    chosen = [p for p in ordered if not path_matches(p, ignore)][:limit]
    dropped = [p for p in ordered if p not in chosen]

    share = acc.limits["changed_files"]
    per_file = max(2000, share // max(1, len(chosen)))
    parts: list[str] = []

    for rel in chosen:
        text = read_source(root, gh, repo, sha, rel)
        if text is None:
            parts.append(f"### {rel}\n(skipped: unreadable, binary, or over {MAX_SOURCE_BYTES} bytes)\n")
            continue
        body = text if len(text) <= per_file else windowed(text, merge_ranges(ranges[rel], WINDOW_PAD))
        if len(body) > per_file:
            body = windowed(text, ranges[rel])
        parts.append(f"### {rel}\n```\n{body}\n```\n")

    if dropped:
        parts.append(f"### {len(dropped)} further changed file(s) not shown\n" + "\n".join(f"- {p}" for p in dropped) + "\n")

    if not parts:
        return ""
    header = (
        "## Changed files at head\n\n"
        "Context only. These are the touched files as they stand at the PR head, so you can "
        "see what each hunk sits inside. A finding still anchors to a diff line, never to a "
        "line you first saw here.\n\n"
    )
    return acc.add("changed_files", header + "\n".join(parts))
```

- [ ] **Step 5: Add `max_context_files` to `DEFAULTS` and wire the part into `build_context`**

In `DEFAULTS`:

```python
    "max_context_files": 25,
```

In `build_context`, replacing the `# Parts are filled in Tasks 10-13.` comment:

```python
        sections: list[str] = []
        ranges = diff_paths(diff)
        sections.append(pack_changed_files(
            ctx.root, gh, repo, pr["head"]["sha"], ranges, cfg, acc))
        ctx.pack = "\n".join(s for s in sections if s)
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
python3 -m unittest discover -s tests -t . -v
```

Expected: all PASS (79 tests).

- [ ] **Step 7: Inspect a real pack**

```bash
python3 review.py --diff-file /tmp/x.diff --lens craft --worktree ~/Code/<thatrepo> --save /tmp/t10.json -v 2>&1 | grep -E "context "
python3 -c "
import json; print(json.load(open('/tmp/t10.json'))['pack'][:3000])
"
```

Expected: `context changed_files: <n>/39840 chars`, and a pack showing your changed files with line numbers. Check by eye that the line numbers line up with the diff — an off-by-one here silently misleads every lens.

- [ ] **Step 8: Commit**

```bash
git add review.py tests/test_context.py
git commit -m "feat: pack changed files at head

Whole file where it fits, hunk-centred windows where it does not, with
elisions and line numbers both explicit — a lens needs the numbers to
relate this to the diff, and needs the elisions to know what it has not
seen.

First consumer of ignore_paths, which has been in DEFAULTS unread since
the first commit."
```

---

### Task 11: Pack part — call sites and importers

**Files:**
- Modify: `review.py` — new `DEF_RE`, `SYMBOL_STOPLIST`, `changed_symbols`, `walk_source`, `grep_repo`, `pack_call_sites`; `build_context()`
- Modify: `tests/test_context.py`

**Interfaces:**
- Consumes: `Accounting`, `Context.root`, `path_matches`, `is_binary`
- Produces:
  - `changed_symbols(diff: str) -> list[str]`
  - `grep_repo(root: Path, needles: list[str], cfg: dict, *, exclude: set[str], max_hits: int) -> dict[str, list[tuple[str, int, str]]]`
  - `pack_call_sites(root: Path | None, diff: str, ranges: dict, cfg: dict, acc: Accounting) -> str`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_context.py`:

```python
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


class TestPackCallSites(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.cfg = dict(review.DEFAULTS)
        self.addCleanup(self.tmp.cleanup)

    def acc(self):
        return review.Accounting({"changed_files": 1, "call_sites": 15000, "conventions": 1,
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python3 -m unittest discover -s tests -t . -v
```

Expected: FAIL with `AttributeError: module 'review' has no attribute 'changed_symbols'`.

- [ ] **Step 3: Add symbol extraction**

```python
# Definition-shaped lines across the languages this reviews in practice. Deliberately
# language-agnostic and deliberately imprecise: over-matching is bounded by the hit
# ceiling and the budget, whereas a per-language parser would be a dependency.
DEF_RE = re.compile(
    r"\b(?:def|class|func|fn|type|interface|struct|"
    r"function|export\s+(?:const|function|class|type|interface|default)|const|let|var)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
)

# Names too generic for a grep to say anything useful about.
SYMBOL_STOPLIST = {
    "value", "values", "index", "result", "results", "data", "item", "items", "name",
    "names", "self", "this", "true", "false", "null", "none", "type", "types", "main",
    "test", "tests", "error", "errors", "config", "options", "params", "args", "kwargs",
    "string", "number", "object", "array", "list", "dict", "props", "state", "default",
}
MIN_SYMBOL_LEN = 4
MAX_SYMBOLS = 20
MAX_HITS_PER_SYMBOL = 3
SYMBOL_HIT_CEILING = 40


def changed_symbols(diff: str) -> list[str]:
    """Definition-shaped identifiers on the diff's added and removed lines.

    These are the names whose call sites a reviewer would grep for. Order is
    first-seen so the result is deterministic across runs.
    """
    seen: list[str] = []
    for line in diff.splitlines():
        if not line[:1] in ("+", "-") or line.startswith(("+++", "---")):
            continue
        for m in DEF_RE.finditer(line[1:]):
            name = m.group("name")
            if len(name) < MIN_SYMBOL_LEN or name.lower() in SYMBOL_STOPLIST:
                continue
            if name not in seen:
                seen.append(name)
    return seen[:MAX_SYMBOLS]
```

- [ ] **Step 4: Add the repo grep**

```python
def walk_source(root: Path, cfg: dict):
    """Yield (relpath, text) for every readable text file under `root`."""
    ignore = cfg.get("ignore_paths") or []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith(".git/") or "/.git/" in f"/{rel}":
            continue
        if path_matches(rel, ignore):
            continue
        try:
            if path.stat().st_size > MAX_SOURCE_BYTES:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        if is_binary(data):
            continue
        yield rel, data.decode("utf-8", "replace")


def grep_repo(
    root: Path, needles: list[str], cfg: dict, *, exclude: set[str], max_hits: int
) -> dict[str, list[tuple[str, int, str]]]:
    """needle -> up to `max_hits` (relpath, lineno, line) matches outside `exclude`.

    A needle exceeding SYMBOL_HIT_CEILING total matches is dropped entirely rather
    than sampled: a name that appears everywhere tells a reviewer nothing and would
    crowd out one that appears twice in the file that matters.
    """
    if not needles:
        return {}
    counts = {n: 0 for n in needles}
    hits: dict[str, list[tuple[str, int, str]]] = {n: [] for n in needles}
    for rel, text in walk_source(root, cfg):
        if rel in exclude:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for needle in needles:
                if needle in line:
                    counts[needle] += 1
                    if len(hits[needle]) < max_hits:
                        hits[needle].append((rel, lineno, line.strip()))
    return {n: h for n, h in hits.items() if h and counts[n] <= SYMBOL_HIT_CEILING}
```

- [ ] **Step 5: Add `pack_call_sites`**

```python
def pack_call_sites(
    root: Path | None, diff: str, ranges: dict[str, list[tuple[int, int]]],
    cfg: dict, acc: Accounting,
) -> str:
    """Call sites of changed symbols, and importers of changed modules."""
    if root is None:
        return ""

    changed = set(ranges)
    symbols = changed_symbols(diff)
    # Importers are cheaper and more precise than symbol matching, so they run even
    # when nothing definition-shaped changed.
    modules = []
    for rel in changed:
        stem = rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if len(stem) >= MIN_SYMBOL_LEN and stem.lower() not in SYMBOL_STOPLIST:
            modules.append(stem)

    needles = list(dict.fromkeys(symbols + modules))[:MAX_SYMBOLS]
    found = grep_repo(root, needles, cfg, exclude=changed, max_hits=MAX_HITS_PER_SYMBOL)
    if not found:
        return ""

    parts = []
    for needle, hits in found.items():
        rendered = "\n".join(f"{rel}:{lineno}: {line}" for rel, lineno, line in hits)
        parts.append(f"### `{needle}`\n```\n{rendered}\n```\n")

    header = (
        "## Call sites and importers outside the diff\n\n"
        "Context only, found by grep over the checkout. Use these to judge whether a "
        "changed signature, return shape or invariant breaks something the diff does not "
        "show. Matching is textual, so a hit may be unrelated — read it before relying on "
        "it, and anchor any finding to the diff line that causes the problem.\n\n"
    )
    return acc.add("call_sites", header + "\n".join(parts))
```

**Departure from the spec, ruled before execution:** hits are single lines with `path:line` prefixes rather than the spec's ±8-line windows. Per character of budget this buys more distinct hits, which is what the part is for. No `HIT_PAD` constant is defined — an unused constant is dead code, and if Task 16 shows lenses cannot use bare lines, switching to `windowed()` here is a two-line change anyway.

- [ ] **Step 6: Wire the part into `build_context`**

```python
        sections.append(pack_call_sites(ctx.root, diff, ranges, cfg, acc))
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
python3 -m unittest discover -s tests -t . -v
```

Expected: all PASS (97 tests).

- [ ] **Step 8: Inspect real call sites**

```bash
python3 -c "
import review, pathlib, json
review.DOC = review.Doctrine(pathlib.Path(review.__file__).parent / 'doctrine')
diff = pathlib.Path('/tmp/x.diff').read_text()
print('symbols:', review.changed_symbols(diff))
"
```

Expected: a plausible list of names that the PR actually changed. Nonsense entries mean `DEF_RE` is over-matching for this language — extend `SYMBOL_STOPLIST` rather than loosening the regex.

- [ ] **Step 9: Commit**

```bash
git add review.py tests/test_context.py
git commit -m "feat: pack call sites and importers

Grep the checkout for definition-shaped names the diff changed, plus
importers of each changed module. Symbols over the hit ceiling are
dropped rather than sampled: a name appearing everywhere says nothing and
would crowd out one appearing twice where it matters.

Matching is textual and language-agnostic on purpose — a per-language
parser would be a dependency, and over-matching is bounded by the hit
ceiling and the budget."
```

---

### Task 12: Pack part — conventions and path tree

**Files:**
- Modify: `review.py` — new `CONVENTION_FILES`, `pack_conventions`, `pack_tree`; `build_context()`
- Modify: `tests/test_context.py`

**Interfaces:**
- Consumes: `Accounting`, `Context.root`, `walk_source`
- Produces:
  - `pack_conventions(root: Path | None, ranges: dict, acc: Accounting) -> str`
  - `pack_tree(root: Path | None, ranges: dict, cfg: dict, acc: Accounting) -> str`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_context.py`:

```python
class TestPackConventions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.cfg = dict(review.DEFAULTS)
        self.addCleanup(self.tmp.cleanup)

    def acc(self):
        return review.Accounting({"changed_files": 1, "call_sites": 1, "conventions": 12000,
                                  "requirements": 1, "tree": 6000})

    def test_a_root_claude_md_is_included(self):
        make_tree(self.root, {"CLAUDE.md": "Always use tabs.\n"})
        out = review.pack_conventions(self.root, {"src/a.py": [(1, 1)]}, self.acc())
        self.assertIn("Always use tabs.", out)

    def test_a_nearest_ancestor_file_is_included(self):
        make_tree(self.root, {"web/AGENTS.md": "Web rules.\n"})
        out = review.pack_conventions(self.root, {"web/app/x.py": [(1, 1)]}, self.acc())
        self.assertIn("Web rules.", out)

    def test_readme_is_used_only_when_nothing_else_exists(self):
        make_tree(self.root, {"README.md": "Readme text.\n"})
        out = review.pack_conventions(self.root, {"src/a.py": [(1, 1)]}, self.acc())
        self.assertIn("Readme text.", out)

    def test_readme_is_omitted_when_a_conventions_file_exists(self):
        make_tree(self.root, {"README.md": "Readme text.\n", "CONTRIBUTING.md": "Contribute.\n"})
        out = review.pack_conventions(self.root, {"src/a.py": [(1, 1)]}, self.acc())
        self.assertIn("Contribute.", out)
        self.assertNotIn("Readme text.", out)

    def test_no_checkout_yields_an_empty_section(self):
        self.assertEqual(review.pack_conventions(None, {}, self.acc()), "")


class TestPackTree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.cfg = dict(review.DEFAULTS)
        self.addCleanup(self.tmp.cleanup)

    def acc(self):
        return review.Accounting({"changed_files": 1, "call_sites": 1, "conventions": 1,
                                  "requirements": 1, "tree": 6000})

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

    def test_no_checkout_yields_an_empty_section(self):
        self.assertEqual(review.pack_tree(None, {}, self.cfg, self.acc()), "")
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python3 -m unittest discover -s tests -t . -v
```

Expected: FAIL with `AttributeError: module 'review' has no attribute 'pack_conventions'`.

- [ ] **Step 3: Add `pack_conventions`**

```python
# In precedence order. README is a fallback only: it is usually description rather
# than instruction, and it is often long enough to crowd out the real conventions.
CONVENTION_FILES = ("CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md")
TREE_KEEP_DEPTH = 2


def pack_conventions(root: Path | None, ranges: dict, acc: Accounting) -> str:
    """The conventions documents governing the changed directories."""
    if root is None:
        return ""

    wanted: list[str] = []
    dirs = {""} | {rel.rsplit("/", 1)[0] for rel in ranges if "/" in rel}
    for d in sorted(dirs):
        parts = d.split("/") if d else []
        for depth in range(len(parts), -1, -1):
            prefix = "/".join(parts[:depth])
            for name in CONVENTION_FILES:
                rel = f"{prefix}/{name}" if prefix else name
                if (root / rel).is_file() and rel not in wanted:
                    wanted.append(rel)

    if not wanted and (root / "README.md").is_file():
        wanted.append("README.md")
    if not wanted:
        return ""

    parts_out = []
    for rel in wanted:
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        parts_out.append(f"### {rel}\n{text}\n")

    header = (
        "## Repo conventions\n\n"
        "Context only. These are this repo's own stated rules and are what "
        "\"consistent with the codebase\" means here — they outrank your own preferences.\n\n"
    )
    return acc.add("conventions", header + "\n".join(parts_out))


def pack_tree(root: Path | None, ranges: dict, cfg: dict, acc: Accounting) -> str:
    """A pruned path listing: full detail near the change, shallow elsewhere.

    This is what lets a lens notice the repo already has the helper the PR
    reimplements. Pruned rather than flat-truncated, because an alphabetical cut at
    N characters keeps everything under `a/` and nothing under `s/`.
    """
    if root is None:
        return ""

    near = {rel.rsplit("/", 1)[0] for rel in ranges if "/" in rel}
    keep: list[str] = []
    for rel, _text in walk_source(root, cfg):
        parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
        if parent in near or rel.count("/") < TREE_KEEP_DEPTH:
            keep.append(rel)

    if not keep:
        return ""
    header = (
        "## Path tree (pruned)\n\n"
        "Context only. Full listing for directories the diff touches, shallow elsewhere. "
        "Use it to check whether something already exists before calling it missing.\n\n"
    )
    return acc.add("tree", header + "```\n" + "\n".join(sorted(keep)) + "\n```\n")
```

- [ ] **Step 4: Wire both parts into `build_context`**

```python
        sections.append(pack_conventions(ctx.root, ranges, acc))
        sections.append(pack_tree(ctx.root, ranges, cfg, acc))
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
python3 -m unittest discover -s tests -t . -v
```

Expected: all PASS (106 tests).

- [ ] **Step 6: Inspect the real sections**

```bash
python3 review.py --diff-file /tmp/x.diff --lens craft --worktree ~/Code/<thatrepo> --save /tmp/t12.json -v 2>&1 | grep "context "
```

Expected: non-zero `conventions` and `tree` usage. If `tree` is truncated on a large repo, that is `TREE_KEEP_DEPTH` being too generous for it — note it for Task 16 rather than changing it blind.

- [ ] **Step 7: Commit**

```bash
git add review.py tests/test_context.py
git commit -m "feat: pack repo conventions and a pruned path tree

Conventions are the repo's own stated rules, which is what 'consistent
with the codebase' has to mean. README is a fallback only: usually
description rather than instruction, and long enough to crowd out the
real thing.

The tree is pruned rather than flat-truncated — an alphabetical cut keeps
everything under a/ and nothing under s/."
```

---

### Task 13: Requirements resolution

Replaces `requirements = pr.get("body")`. The one pack part that also reaches the adjudicator, exactly as the plain PR body does today.

**Files:**
- Modify: `review.py` — new `ISSUE_REF_RE`, `issue_refs`, `resolve_requirements`; `build_context()`
- Create: `tests/test_requirements.py`

**Interfaces:**
- Consumes: `Accounting`, `GitHub`
- Produces:
  - `issue_refs(text: str, repo: str) -> list[tuple[str, int]]` returning `(repo, number)` pairs
  - `resolve_requirements(gh, repo: str, pr: dict, acc: Accounting) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_requirements.py`:

```python
"""Requirements resolution. GitHub is stubbed; nothing here touches the network."""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import review  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python3 -m unittest discover -s tests -t . -v
```

Expected: FAIL with `AttributeError: module 'review' has no attribute 'issue_refs'`.

- [ ] **Step 3: Add reference parsing**

```python
# `#42`, `Closes #42`, and full issue/PR URLs including cross-repo ones. The
# negative lookbehind keeps hex colours and anchors from parsing as references.
ISSUE_REF_RE = re.compile(
    r"https?://github\.com/(?P<orepo>[\w.-]+/[\w.-]+)/(?:issues|pull)/(?P<onum>\d+)"
    r"|(?<![\w#])#(?P<num>\d{1,7})\b"
)
MAX_LINKED_ISSUES = 5


def issue_refs(text: str, repo: str) -> list[tuple[str, int]]:
    """(repo, number) pairs referenced by `text`, deduplicated, first-seen order."""
    out: list[tuple[str, int]] = []
    for m in ISSUE_REF_RE.finditer(text or ""):
        ref = (m.group("orepo"), int(m.group("onum"))) if m.group("orepo") else (repo, int(m.group("num")))
        if ref not in out:
            out.append(ref)
    return out[:MAX_LINKED_ISSUES]
```

- [ ] **Step 4: Add `resolve_requirements`**

```python
def resolve_requirements(gh, repo: str, pr: dict, acc: Accounting) -> str:
    """The PR body plus its linked issues and any human conversation comments.

    Requirements resolution was `pr.get("body")`, which meant the requirements lens
    judged conformity against whatever the author chose to write. This is the one
    pack part that also reaches the adjudicator, exactly as the plain body does
    today — see doctrine/agents/pr-review-verdict.md.

    Every GitHub failure degrades to what we already had. A thinner requirements
    string is worth far more than a failed review.
    """
    body = (pr.get("body") or "").strip()
    parts = [body] if body else ["(none stated — judge against the PR title alone)"]

    if gh is not None:
        for ref_repo, number in issue_refs(f"{pr.get('title', '')}\n{body}", repo):
            try:
                issue = gh.get(f"/repos/{ref_repo}/issues/{number}")
            except Exception as exc:  # noqa: BLE001
                vlog(f"    context: could not fetch {ref_repo}#{number}: {exc}")
                continue
            parts.append(
                f"### Linked issue {ref_repo}#{number}: {issue.get('title', '')}\n"
                f"{(issue.get('body') or '(empty)').strip()}"
            )

        try:
            comments = gh.get(f"/repos/{repo}/issues/{pr['number']}/comments")
        except Exception as exc:  # noqa: BLE001
            vlog(f"    context: could not fetch PR comments: {exc}")
            comments = []
        human = [
            c for c in comments
            if (c.get("user") or {}).get("type") != "Bot"
            and not ((c.get("user") or {}).get("login", "")).endswith("[bot]")
        ]
        if human:
            rendered = "\n\n".join(
                f"**{(c.get('user') or {}).get('login', '?')}**: {(c.get('body') or '').strip()}"
                for c in human
            )
            parts.append(
                "### Human comments on this PR\n"
                "Requirements as stated by people, not by the description.\n\n" + rendered
            )

    return acc.add("requirements", "\n\n".join(parts))
```

- [ ] **Step 5: Wire it into `build_context`**

Requirements are resolved before the other parts, because `Accounting` must record them and `ctx.requirements` is consumed separately from `ctx.pack`. Replace the `Context(...)` construction and add after `acc` is created:

```python
        ctx.requirements = resolve_requirements(gh, repo, pr, acc)
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
python3 -m unittest discover -s tests -t . -v
```

Expected: all PASS (121 tests).

- [ ] **Step 7: Verify against a real PR with a linked issue**

```bash
python3 review.py <owner/repo>#<PR-with-a-linked-issue> --force -v 2>&1 | grep -E "context requirements|context note"
python3 review.py <owner/repo>#<PR-with-a-linked-issue> --force --save /tmp/t13.json -v
python3 -c "import json; print(json.load(open('/tmp/t13.json'))['requirements'][:2000])"
```

Expected: the linked issue's title and body present, and any human comments attributed by login. This is a dry run — nothing posts without `--post`.

- [ ] **Step 8: Commit**

```bash
git add review.py tests/test_requirements.py
git commit -m "feat: resolve requirements from linked issues and human comments

Requirements resolution was pr.get('body'), so the requirements lens
judged conformity against whatever the author chose to write. Now the
body plus up to five linked issues plus human PR comments, with bots
filtered out — a person saying 'not that way' is requirements signal no
lens could previously see.

This is the one pack part that also reaches the adjudicator, exactly as
the plain body does today."
```

---

### Task 14: Doctrine porting note

The lens is now given context, so the porting note that revokes it is wrong. `CLAUDE.md` confines deployment caveats to this note and the user-message tail — the shared doctrine stays verbatim for upstream parity.

**Files:**
- Modify: `doctrine/agents/pr-review-lens.md:1-24`

**Interfaces:**
- Consumes: `LENS_TAIL` from Task 3 (the note must not contradict it)
- Produces: nothing programmatic

- [ ] **Step 1: Rewrite bullet 1 of the porting note**

Replace the first bullet (`**You have no tools and no worktree.**` through `...does harm.`) with:

```markdown
> - **You have no tools, but you are given context.** Upstream gave you
>   `Read`/`Grep`/`Glob` over a read-only checkout at the PR head. Here that checkout is
>   read for you and pushed into your prompt as context sections after the diff: the
>   changed files as they stand at head, call sites and importers found by grep, this
>   repo's own conventions documents, and a pruned path tree. Where the doctrine below
>   tells you to consult the worktree, consult those sections instead.
>
>   They are bounded, so they are not the whole repo. A section may be absent, and a
>   section may carry a truncation marker (`… 340 lines elided …`, `… truncated: … budget …`).
>   **Treat anything not shown as code you have not seen.** Do not speculate about it: if a
>   finding depends on something outside both the diff and the context sections, omit it, or
>   file it as `advisory` and say in `consequence` that it is unverified. A confident claim
>   about an unseen call site is still the main way this agent does harm.
>
>   Grep matching is textual, so a listed call site may be unrelated to the symbol you care
>   about. Read it before you rely on it.
```

- [ ] **Step 2: Rewrite the closing paragraph**

Replace `> Ignore any instruction below about receiving a `diff_path`, `worktree`, or brief paths: the briefs are already concatenated into this prompt, and the diff is in the user message.` with:

```markdown
> Ignore any instruction below about receiving a `diff_path`, a `worktree`, or brief paths,
> and ignore the Do-steps that tell you to read files from them — you have no tools to read
> anything with, and everything they name is already in this prompt. `_shared.md` is in this
> system prompt above; the diff and the context sections are in the user message; your own
> lens brief is at the end of the user message, immediately before the closing instruction.
> You already have all three. Nothing needs fetching.
```

- [ ] **Step 3: Verify the doctrine still loads and the lens still returns a valid envelope**

```bash
python3 review.py --diff-file /tmp/x.diff --lens correctness --worktree ~/Code/<thatrepo> -v
```

Expected: a schema-valid envelope. Read the `notes` field — a lens complaining that it cannot find its brief or the worktree means the note is still contradicting the prompt's actual shape.

- [ ] **Step 4: Confirm the shared doctrine is untouched**

```bash
git diff --stat main -- doctrine/
```

Expected: only `doctrine/agents/pr-review-lens.md`. Any other file listed breaks upstream parity with the `pr-reviewer` plugin and must be reverted.

- [ ] **Step 5: Commit**

```bash
git add doctrine/agents/pr-review-lens.md
git commit -m "docs(doctrine): the lens now gets context, not just a diff

The porting note revoked the worktree the doctrine below it assumes. That
is no longer true: the checkout is read deterministically and pushed into
the prompt. Tells the lens where each piece now lives, and that absence
or a truncation marker means code it has not seen.

Confined to the porting note — the shared doctrine and lens briefs stay
verbatim for parity with the upstream pr-reviewer plugin."
```

---

### Task 15: Documentation

`CLAUDE.md` currently states several things this branch has made false. Leaving them is worse than never having written them, because the next session trusts them.

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: everything
- Produces: nothing programmatic

- [ ] **Step 1: Correct the false claims in `CLAUDE.md`**

Four statements are now wrong or incomplete:

1. **"What this is"** says "no test suite". Replace with a description of the stdlib `unittest` suite and the `python3 -m unittest discover -s tests -t . -v` command, noting the deployment still installs nothing.
2. **"There is nothing to lint or test against"** — replace with: unit tests cover the deterministic pack and prompt-assembly helpers; model-calling paths are still verified by offline A/B against a diff you know.
3. **"The adjudicator never sees the diff"** — extend to the pack: the four pack parts never reach it, the enriched requirements string does, exactly as the plain body did.
4. **"Prompt composition"** — the lens prompt is now three blocks, shared-first, with the lens brief in the user message. State that blocks 1-2 must stay byte-identical across lenses and that `tests/test_prompting.py` enforces it.

Add to the **Invariants** list:

```markdown
- **The pack must never fail a review.** Every acquisition and assembly path degrades to a
  smaller pack, then to no pack. A thin review beats no review.
- **Blocks 1 and 2 of the lens prompt must be byte-identical across the three lenses.** One
  lens-dependent character and all three calls miss the cache. Never interpolate anything
  lens-specific above the tail block.
```

- [ ] **Step 2: Update `README.md`**

- **Commands:** add `--worktree`, `--no-context`, `--no-cache`, and the unittest command.
- **Configuration:** document `context`, `max_context_chars`, `max_context_files`, `max_tarball_bytes`, `cache`, and that `ignore_paths` is now actually read.
- **Cost:** replace the `$0.11 per PR` figure with the measured numbers from Tasks 6 and 16. Do not guess — quote what you saw.
- **Deployment:** note that the pack needs outbound access to `codeload.github.com` for the tarball, which the per-file fallback does not.

- [ ] **Step 3: Verify the documented commands actually work**

```bash
python3 -m unittest discover -s tests -t . -v
python3 review.py --help | grep -E "no-context|no-cache|worktree"
```

Expected: all tests pass and all three flags appear in the help text.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: update for the context pack, caching and the test suite

CLAUDE.md claimed no test suite, nothing to test against, and a prompt
composition that no longer matches. Stale guidance is worse than none
because the next session trusts it.

Adds two invariants: the pack must never fail a review, and the first two
prompt blocks must stay byte-identical across lenses."
```

---

### Task 16: Gate 2 — verify the pack, and gate 3 — degradation

The final gate. Answers whether the pack earns its cost, and confirms nothing about it can break a review.

**Files:**
- Reads: `/tmp/x.diff`
- Create: `/tmp/before.json`, `/tmp/after.json`

**Interfaces:**
- Consumes: everything
- Produces: a keep/tune/revert decision, and the measured cost figures Task 15 documents

- [ ] **Step 1: Run the A/B over the same diff**

```bash
python3 review.py --diff-file /tmp/x.diff --no-context --save /tmp/before.json -v 2>&1 | tee /tmp/before.log
python3 review.py --diff-file /tmp/x.diff --worktree ~/Code/<thatrepo> --save /tmp/after.json -v 2>&1 | tee /tmp/after.log
```

- [ ] **Step 2: Compare the findings**

```bash
python3 - <<'EOF'
import json
for name in ("before", "after"):
    d = json.load(open(f"/tmp/{name}.json"))
    print(f"--- {name}  pack={len(d.get('pack') or '')} chars")
    for e in sorted(d["envelopes"], key=lambda e: e["lens"]):
        print(f'  {e["lens"]:14} findings={len(e["findings"]):2} '
              f'blocking={sum(1 for f in e["findings"] if f["severity"] == "blocking")}')
        for f in e["findings"]:
            print(f'      [{f["severity"]:8}] {f["path"]}:{f["line"]} {f["claim"][:70]}')
    print("  verdict:", d["verdict"]["verdict"], d["verdict"]["blocker_count"])
EOF
```

Read for the question that matters: **did new findings appear that genuinely needed context?** A finding citing a caller, a repo convention or an existing utility is the pack working. More findings of the same kind the diff alone would have produced is the pack merely making the prompt longer — and if that is all you see, the honest conclusion is that the pack is not earning 2x and its budgets should shrink.

- [ ] **Step 3: Check the anchor-violation count against Task 8's baseline**

```bash
grep -E "anchors:|anchored outside" /tmp/before.log /tmp/after.log
```

Expected: no worse than the number Task 8 recorded. A rise means the pack is tempting lenses to cite code they only read as context — tighten the third paragraph of `LENS_TAIL` before anything else.

- [ ] **Step 4: Check which budgets bit**

```bash
grep "context " /tmp/after.log
```

Read each part. `empty` on a part that should have content is a bug in that part, not a budget problem. `TRUNCATED` on `changed_files` for a large PR is expected and fine. `TRUNCATED` on `tree` means `TREE_KEEP_DEPTH` is too generous for this repo.

- [ ] **Step 5: Record the real cost**

```bash
grep -E "sending ~|cached=" /tmp/before.log /tmp/after.log
```

Compute input tokens with and without the pack, and with and without cache reads. These are the numbers Task 15 puts in the README — the spec's ~2x and ~50% are estimates, and the README should quote measurements.

- [ ] **Step 6: Confirm degradation cannot break a review**

```bash
# a worktree that does not exist
python3 review.py --diff-file /tmp/x.diff --lens craft --worktree /nonexistent -v 2>&1 | grep -E "context note|OFFLINE"
# a directory that is not a checkout
python3 review.py --diff-file /tmp/x.diff --lens craft --worktree /tmp -v 2>&1 | tail -5
# force the per-file API fallback on a real PR
python3 review.py <owner/repo>#<PR> --force -v 2>&1 | grep -E "context|degrading"
```

For the third, temporarily set `"max_tarball_bytes": 1000` in `DEFAULTS`, confirm you see `exceeded 1000 bytes; degrading` followed by a completed review with a smaller pack, then **restore the default**.

- [ ] **Step 7: Confirm the whole suite still passes and the invariant holds**

```bash
python3 -m unittest discover -s tests -t . -v
grep -n "adjudicate(" review.py
```

Expected: all tests pass, and `adjudicate` is called with `ctx.requirements` and never with `ctx.pack`.

- [ ] **Step 8: Restore anything the gate changed, and commit any tuning**

```bash
git diff
```

Expected: empty, unless Step 4 or Step 6 led to a deliberate tuning change. Commit those separately with the measurement that justified them:

```bash
git add review.py
git commit -m "tune: <what> after measuring on <repo>#<PR>

<the number that justified it>"
```

---

## Self-review

**Spec coverage.** Every spec section maps to a task: Acquisition → 9; Degradation ladder → 9, 16; Pack contents (five parts) → 10, 11, 12, 13; Prompt placement → 3; Prompt caching, staggered dispatch, mechanics, provider risk → 2, 4, 5, 6; What reaches the adjudicator → 9 (comment and call site), 13; Code shape → 7-13; Configuration → 5, 9; Anchor validation → 7, 8; Doctrine changes → 14; Verification steps 1-3 → 6, 16.

**Two deliberate departures from the spec**, both recorded above where they occur:

1. **Call-site hits are single lines with `path:line` prefixes, not ±8-line windows** (Task 11, Step 5). Per character of budget this buys more distinct hits, which is what the part is for. Switching to `windowed()` is a two-line change if Task 16 shows lenses cannot use bare lines.
2. **`max_context_files` became a config key** rather than a bare constant (Task 10), because it is the knob most likely to need per-repo tuning on a monorepo.

**Two pre-flight rulings** (asked and answered before execution began, so a reviewer flagging either is reading a stale plan):

- **No `HIT_PAD` constant.** An earlier draft defined one it never used, as a signpost for the spec's ±8 lines. An unused constant is dead code; it was removed.
- **`pack_conventions` takes no `cfg`.** An earlier draft gave it one for signature symmetry with the other `pack_*` functions and never read it. Signature symmetry does not justify an unused parameter.

**One spec value not yet measured:** the spec's ~2x cost and ~50% caching saving are estimates. Task 16 Step 5 measures them and Task 15 documents the real figures.

**Pre-verified code blocks.** The pure helpers in Tasks 7, 10, 11 and 13 were extracted and run against this plan's own tests before it was committed — `_hunks`, `diff_paths`, `diff_anchors` (12 tests), and `changed_symbols`, `issue_refs`, `path_matches`, `merge_ranges`, `windowed` (27 tests). All 39 pass as written, so a failure in those steps means the code was transcribed differently, not that the plan is wrong.

Three bugs were found and fixed that way, all of which would otherwise have surfaced as confusing red tests mid-implementation:

- The `TWO_FILES` fixture's hunk header did not match its body, and the expected RIGHT-side range was off by one.
- `_hunks` keyed only on `+++ b/path`, so a deleted file produced no anchors at all — but the spec requires `LEFT` anchors, which GitHub does accept on deleted files. It now tracks both paths.
- Two tests asserted behaviour the constants forbid: a 10-hit symbol does not cross the 40-hit ceiling, and a module stem of `api` is below `MIN_SYMBOL_LEN` so contributes no importer needle.
