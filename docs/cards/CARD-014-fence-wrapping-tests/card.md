---
id: CARD-014
type: task
layer: core
reqs: [REQ-022, REQ-025]
title: Convert the diff-fence wrapping tests and their fence fixtures
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-013]
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
estimated_lines: 288
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
`TestDiffFenceWrapping` pins the diff-fence wrapping of the lens prompt — an invariant `CLAUDE.md` documents, and one that cannot be left behind in `tests/test_prompting.py` while `build_lens_prompt` moves into `core/prompt.py`.

## Acceptance criteria
- [ ] `TestDiffFenceWrapping` and its four fence fixtures (`tests/test_prompting.py:196-305`) live under `tests/core/` (REQ-025)
- [ ] `tests/helpers.py` holds `unclosed_fence` and `make_tree`, and every consumer imports them from there rather than from `tests/test_context.py` (REQ-025)
- [ ] Goldens are byte-identical (REQ-022)

## Notes
Split out of CARD-013 because the two together are ~688 changed lines (intake run 3, finding F4).

`tests/helpers.py` is created here rather than at CARD-031/CARD-033 because this is the first card that needs `unclosed_fence` away from `tests/test_context.py`, and CARD-033 has only 8 lines of headroom (intake run 4, advisory A6). `make_tree` comes along for the same reason.
