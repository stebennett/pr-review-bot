---
id: CARD-033
type: task
layer: adapters
reqs: [REQ-003, REQ-012, REQ-025]
title: TarballTree and ApiTree complete the ladder
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-016]
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
estimated_lines: 492
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
With these two, all four acquisition rungs are `SourceTree` implementations and the degradation ladder is a choice of type rather than branching. `ApiTree` in particular shows why a partial implementation is a first-class thing.

## Acceptance criteria
- [ ] All four rungs are `SourceTree` implementations (REQ-003)
- [ ] `ApiTree` serves `read()` and returns emptiness from `walk`/`grep`; the pack still states in band what is missing (REQ-003)
- [ ] `tarfile`'s `filter="data"` is preserved (REQ-012)
- [ ] `TestExtractCheckout` and `TestStreamCapped` (`tests/test_context.py:183-252`) and `make_archive` (`:50-58`) move with them (REQ-025)

## Notes
**`tarfile`'s `filter="data"` is load-bearing** on the 3.13 deployment, where `None` still means `fully_trusted`. It is what refuses path traversal. Never remove it because a local 3.14 test passes without it.

The pack stating in band what is missing is what stops a lens reading absence as evidence when `ApiTree` cannot walk or grep.

At 492 against a 500 ceiling this is the tightest card on the board and **must not receive another line** (intake run 4). `make_tree` therefore lives in `tests/helpers.py` from CARD-014 rather than moving here with `make_archive`.
