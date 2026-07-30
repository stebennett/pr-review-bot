---
id: CARD-013
type: task
layer: core
reqs: [REQ-001, REQ-007, REQ-022, REQ-025]
title: Extract core/prompt; the cache prefix becomes inexpressible
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-007, CARD-008, CARD-010, CARD-012]
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
estimated_lines: 462
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
Blocks 1 and 2 of the lens prompt must be byte-identical across the three lenses, and the failure is silent — nothing breaks, the cost doubles. Today a test asserts it. Splitting the builder so the shared half has no `lens` parameter makes lens-dependence in the cached prefix not merely detected but impossible to express.

## Acceptance criteria
- [ ] `build_shared_blocks` has no `lens` parameter, verified by `inspect.signature` (REQ-007)
- [ ] `build_lens_tail(lens, brief)` builds block 3 alone (REQ-007)
- [ ] `seg` (`review.py:386-398`) and `_blocks` (`:399-402`) live in `core/prompt.py`, and `TestSeg` (`tests/test_prompting.py:18-36`) travels with them (REQ-001, REQ-025)
- [ ] The shared `DIFF` and `PR` fixtures (`tests/test_prompting.py:88-106`) move with this card; `TestDiffFenceWrapping` and `TestAdjudicatePrompt` import them from the new location (REQ-025)
- [ ] Goldens are byte-identical across all three lenses (REQ-022)

## Notes
`seg` and `_blocks` go here rather than following the OpenRouter section into `adapters/`: they are pure, they are prompt structure, and `build_shared_blocks` must call `seg` from `core/` — the boundary test would fail on the first prompt card otherwise. `strip_fence` correctly stays with the adapter, because it parses a model *response*, not a prompt.

The existing assertion in `tests/test_prompting.py` stays as a second line of defence even once the structure makes the violation inexpressible.
