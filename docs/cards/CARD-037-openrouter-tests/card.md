---
id: CARD-037
type: task
layer: adapters
reqs: [REQ-005, REQ-025]
title: Convert the completion-payload and fence-stripping tests
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-036]
branch: ""
worktree: ""
design_pr_url: ""
pr_urls: []
split_slices: 0
adrs: []
reworks:
  slice: 0
  design: 0
  implement: 0
  split: 0
  deliver: 0
review_lenses_failed: []
estimated_lines: 170
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
The payload shape and response fence-stripping are the two behaviours of the OpenRouter adapter that a silent regression would hide, so their tests move with the module rather than being left behind.

## Acceptance criteria
- [ ] `TestCompletionPayload` and `TestStripFence` (`tests/test_prompting.py:37-86`) live under `tests/adapters/` (REQ-025)
- [ ] They exercise `adapters/openrouter.py` through `ModelClient`, with no network call (REQ-005)

## Notes
Scope is `TestCompletionPayload` and `TestStripFence` **only**. `TestSeg` travels with CARD-013 instead, because `seg` moves to `core/prompt.py` — an earlier proposal grouped all three on one card (intake run 3, finding F6; run 4, advisory A2).

Split out of CARD-036 because the two together breach the ceiling.
