---
id: CARD-048
type: task
layer: app
reqs: [REQ-001, REQ-025]
title: Convert TestCheckoutMatchesDiff
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-045]
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
estimated_lines: 252
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
`--worktree` is validated against the diff's pre-existing changed paths, and this is the test class that pins that predicate — including the case a directory that is not a checkout of the repo under review must fail.

## Acceptance criteria
- [ ] `TestCheckoutMatchesDiff` (`tests/test_context.py:557-682`) lives under `tests/app/` (REQ-025)
- [ ] It imports `make_tree` from `tests/helpers.py` (REQ-025)

## Notes
`--worktree` is validated against **pre-existing** changed paths, not all paths: a PR that only adds files has none to check, and rejecting it would discard the pack for no reason. A directory that is not a checkout of the repo under review degrades to no checkout with a note, rather than producing plausible-but-wrong context.

`make_tree` lives in `tests/helpers.py` from CARD-014, so this card only converts the test class (intake run 4, advisory A6).
